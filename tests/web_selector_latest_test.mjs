// The actual browser game opens its selector at earned progress, then keeps
// the level the player left or advanced from in view. Scrolling stays free.
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {driverSetup} from './web_driver.mjs';

const root = process.env.WEB_TEST_ROOT || new URL('../build/web/', import.meta.url).pathname;
const fixture = execFileSync(new URL('../build/guide-test/native', import.meta.url).pathname, ['74'], {encoding: 'utf8'});
const campaign = JSON.parse(await readFile(new URL('../levels/approved.json', import.meta.url), 'utf8'));
const levelOneSolution = campaign.levels[0].solution;
const scenes = JSON.parse(await readFile(new URL('../assets/shovey/world-map/scenes.json', import.meta.url), 'utf8'));
// The v5 portrait map: level 1's authored centre and each painting's authored bounds.
const mapArt = {first: scenes.nodes.portrait[0], panels: scenes.scenes.map(scene => scene.portrait.world_bounds_before_zoom)};
// Fish wander between frames and are persisted with the next player move.
// Compare every other saved field, including objects and the water beneath
// each fish, and require each fish species' population to remain unchanged.
function stationaryCampaign(text) {
  const positionAt = text.indexOf('P');
  assert(positionAt > 0, 'Campaign position is missing');
  const cells = text.split(''), fish = [0, 0, 0];
  for (let cell = 0; cell < 240; cell++) {
    const at = positionAt + 32 + cell * 6;
    const kind = parseInt(text.slice(at, at + 2), 16);
    if (kind < 89 || kind > 91) continue;
    fish[kind - 89]++;
    assert(parseInt(text.slice(at + 4, at + 6), 16) <= 4, 'Invalid fish facing');
    cells.splice(at, 2, '4', '0'); // ShoveyFish rests on water (64).
    cells.splice(at + 4, 2, '0', '4');
  }
  return {state: cells.join(''), fish};
}
const profile = await mkdtemp(join(tmpdir(), 'shovey-selector-'));
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (path.includes('..')) throw Error('Invalid path');
    response.setHeader('Content-Type', path.endsWith('.wasm') ? 'application/wasm' : path.endsWith('.js') ? 'application/javascript' : 'application/octet-stream');
    if (path === '/' || path.endsWith('.html')) response.setHeader('Content-Type', 'text/html');
    response.end(await readFile(join(root, path === '/' ? 'index.html' : path)));
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const target = `http://127.0.0.1:${server.address().port}/`;
const environment = {...process.env};
for (const key of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY']) delete environment[key];
const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], {detached: true, env: environment, stdio: ['ignore', 'ignore', 'pipe']});
let errors = '', socket, sequence = 0;
browser.stderr.on('data', value => errors = (errors + value).slice(-3000));
try {
  let port;
  for (let end = Date.now() + 30000; Date.now() < end && !port;) {
    try { port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; }
    catch { assert.equal(browser.exitCode, null, errors); await delay(50); }
  }
  assert(port, errors);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener('open', resolve, {once: true}));
  const pending = new Map(), failures = [];
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') failures.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
  });
  async function call(method, params = {}) {
    const id = ++sequence;
    const result = new Promise((resolve, reject) => {
      pending.set(id, resolve);
      setTimeout(() => { if (pending.delete(id)) reject(Error(method + ' timed out')); }, 20000).unref();
    });
    socket.send(JSON.stringify({id, method, params}));
    const message = await result;
    assert(!message.error, JSON.stringify(message.error));
    return message.result;
  }
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, returnByValue: true});
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  async function wait(predicate, message) {
    for (let end = Date.now() + 30000; Date.now() < end;) {
      if (await predicate()) return;
      await delay(80);
    }
    throw Error(message + '; browser errors: ' + failures.join('|'));
  }
  let serial = 0;
  async function tree() {
    const command = (++serial) + '\ttree\n';
    await evaluate(`Module.FS.writeFile('/tmp/test-driver/command', ${JSON.stringify(command)})`);
    await wait(() => evaluate(`Module.FS.analyzePath('/tmp/test-driver/reply').exists`), 'No UI driver response');
    const reply = JSON.parse(await evaluate(`Module.FS.readFile('/tmp/test-driver/reply', {encoding:'utf8'})`));
    await evaluate(`Module.FS.unlink('/tmp/test-driver/reply')`);
    assert(reply.ok, JSON.stringify(reply));
    return reply.nodes;
  }
  async function press(label) {
    const node = (await tree()).find(node => node.label === label && (node.role === 'button' || node.kind === 'button'));
    assert(node, 'Missing button: ' + label);
    const x = node.x + node.width / 2, y = node.y + node.height / 2;
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1});
    await delay(80);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1});
    await delay(200);
  }
  async function key(code, keyCode) {
    for (const type of ['keyDown', 'keyUp']) {
      await call('Input.dispatchKeyEvent', {type, key: code, code, windowsVirtualKeyCode: keyCode});
    }
    await delay(80);
  }
  async function wheelToFirst() {
    const [firstX, firstY] = mapArt.first;
    // One probe picks the wheel direction that heads back along the road.
    let backward = 1, previous = Infinity, probed = false;
    for (let attempt = 0; attempt < 64; attempt++) {
      const nodes = await tree();
      const viewport = nodes.find(node => node.key === 20105);
      assert(viewport, 'Map viewport is missing');
      const waypoint = nodes.find(node => node.key === 33001 && node.visible && node.enabled);
      if (waypoint && waypoint.x >= viewport.x && waypoint.x + waypoint.width <= viewport.x + viewport.width &&
          waypoint.y >= viewport.y && waypoint.y + waypoint.height <= viewport.y + viewport.height) return;
      // Infer the camera's actual translation from a submitted v5 painting.
      // The wheel follows the road; no focus, selection or camera state is injected.
      const panel = nodes.find(node => node.kind === 'image' && node.key >= 60001 && node.key < 60001 + mapArt.panels.length);
      assert(panel, 'No map painting available to measure manual scrolling');
      const [authoredX, authoredY, authoredWidth] = mapArt.panels[panel.key - 60001];
      const scale = panel.width / authoredWidth;
      const distance = Math.hypot(panel.x + (firstX - authoredX) * scale - (viewport.x + viewport.width / 2),
        panel.y + (firstY - authoredY) * scale - (viewport.y + viewport.height / 2));
      if (!probed && previous !== Infinity) { probed = true; if (distance > previous + 1) backward = -1; }
      previous = distance;
      const x = viewport.x + viewport.width / 2, y = viewport.y + viewport.height / 2;
      await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x, y, buttons: 0});
      await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x, y, deltaX: 0, deltaY: 240 * backward});
      await delay(350);
    }
    throw Error('Manual wheel navigation along the road did not reveal level 1');
  }
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.addScriptToEvaluateOnNewDocument', {source: driverSetup});
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await call('Page.navigate', {url: target});
  await wait(() => evaluate(`globalThis.Module?.FS?.analyzePath('/tmp/test-driver').exists && document.querySelector('#loading-screen').classList.contains('is-hidden')`), 'Game did not load');
  await wait(async () => (await tree()).some(n => n.label === 'Play' && n.kind === 'button'), 'Fresh Play cover did not appear');
  await press('Play');
  for (let step = 0; step < 10; step++) {
    const nodes = await tree();
    if (nodes.some(n => n.label === 'Not now')) await press('Not now');
    else if (nodes.some(n => n.label === 'Swipe and tap')) await press('Swipe and tap');
    else if (nodes.some(n => n.label === 'Got it')) break;
    else await delay(100);
  }
  await wait(async () => (await tree()).some(n => n.label === 'Got it'), 'Pip introduction did not appear');
  const introduction = await tree();
  assert(introduction.some(n => n.label === 'Pip' && n.kind === 'image'), 'Pip artwork is missing');
  const beforeSnapshot = stationaryCampaign(await evaluate(`Module.FS.readFile('/kryon-apps/shovey/local.campaign', {encoding:'utf8'})`));
  const beforeTip = beforeSnapshot.state;
  // Pip leaves keyboard play available. On level 1 the cell to the right
  // is empty: one key changes only player, facing and move count in the
  // saved position (engine.zi), keeping earned progress and the stationary
  // board. Independently wandering fish retain their species and counts.
  const positionAt = beforeTip.indexOf('P');
  assert(positionAt > 0, 'Campaign position is missing');
  assert.equal(beforeTip.slice(positionAt + 12, positionAt + 20), '00000000');
  const nextPlayer = (parseInt(beforeTip.slice(positionAt + 4, positionAt + 6), 16) + 1).toString(16).padStart(2, '0');
  const expectedTip = beforeTip.slice(0, positionAt + 4) + nextPlayer + '02' +
    beforeTip.slice(positionAt + 8, positionAt + 12) + '00000001' + beforeTip.slice(positionAt + 20);
  await call('Input.dispatchKeyEvent', {type:'keyDown', key:'ArrowRight', code:'ArrowRight', windowsVirtualKeyCode:39, nativeVirtualKeyCode:39});
  await call('Input.dispatchKeyEvent', {type:'keyUp', key:'ArrowRight', code:'ArrowRight', windowsVirtualKeyCode:39, nativeVirtualKeyCode:39});
  await delay(200);
  const afterTip = await evaluate(`Module.FS.readFile('/kryon-apps/shovey/local.campaign', {encoding:'utf8'})`);
  assert.deepEqual(stationaryCampaign(afterTip), {state: expectedTip, fish: beforeSnapshot.fish},
    'Keyboard play under Pip must save exactly one rightward step, preserving progress, fish populations and the stationary board');
  assert((await tree()).some(n => n.label === 'Got it'), 'Movement dismissed Pip');
  await press('Got it');
  await wait(async () => !(await tree()).some(n => n.label === 'Got it'), 'Pip did not dismiss');
  assert.equal(await evaluate(`Module.FS.readFile('/kryon-apps/shovey/local.campaign', {encoding:'utf8'})`), afterTip,
    'Dismissing Pip must not move Shovey');
  assert.equal(await evaluate(`Module.FS.readFile('/kryon-apps/shovey/local.guide.seen', {encoding:'utf8'})`), 'G100000001');
  await call('Runtime.evaluate', {awaitPromise: true, expression: `new Promise(resolve => {
    Module.FS.mkdirTree('/kryon-apps/shovey');
    Module.FS.writeFile('/kryon-apps/shovey/local.campaign', ${JSON.stringify(fixture)});
    Module.FS.writeFile('/kryon-apps/shovey/local.guide.seen', 'G1ffffffff');
    Module.FS.writeFile('/kryon-apps/shovey/controls', 'off');
    Module.FS.writeFile('/kryon-apps/shovey/level-updates', 'off');
    Module.FS.syncfs(false, resolve);
  })`});
  await call('Page.reload');
  await wait(() => evaluate(`globalThis.Module?.FS?.analyzePath('/tmp/test-driver').exists && document.querySelector('#loading-screen').classList.contains('is-hidden')`), 'Game did not reload');
  await wait(async () => (await tree()).some(n => n.label === 'Play' && (n.role === 'button' || n.kind === 'button')), 'Play cover did not appear');
  await press('Play');
  await wait(async () => (await tree()).some(n => n.label.startsWith('Level 74 /')), 'Earned level did not open');
  const arrows = [['ArrowLeft', 37], ['ArrowUp', 38], ['ArrowRight', 39], ['ArrowDown', 40]];
  for (const [index, [width, height]] of [[390, 844], [960, 600]].entries()) {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: true});
    await delay(250);
    await press('Levels');
    const focusedCard = index === 0 ? 33074 : 33002;
    await wait(async () => (await tree()).some(n => n.key === focusedCard && n.y >= 70 && n.y + n.height <= height),
      'Expected selector focus card is not visible');
    await wheelToFirst();
    await delay(500);
    assert((await tree()).some(n => n.key === 33001 && n.visible && n.enabled), 'Selector snapped back during manual scrolling');
    await press('1');
    await wait(async () => (await tree()).some(n => n.label.startsWith('Level 1 /')), 'Older level did not open');
    await press('Levels');
    await wait(async () => (await tree()).some(n => n.key === 33001 && n.y >= 70 && n.y + n.height <= height),
      'Returning from level 1 moved its selector card out of view');
    if (index === 0) {
      await press('Back');
      for (const direction of levelOneSolution) await key(...arrows[Number(direction)]);
      await wait(async () => (await tree()).some(n => n.label.startsWith('Level 2 /')), 'Winning level 1 did not advance to level 2');
      await press('Levels');
      await wait(async () => (await tree()).some(n => n.key === 33002 && n.y >= 70 && n.y + n.height <= height),
        'Finishing level 1 did not keep level 2 in view');
    }
    await press('Continue');
  }
  assert.equal(failures.length, 0, failures.join('|'));
  console.log('Pip artwork, keyboard play, touch dismissal without movement and saved acknowledgement; selector: earned level74 opens once, then replayed level1 and finished level2 stay visible in portrait/landscape');
} finally {
  if (socket) socket.close();
  if (browser.exitCode === null && browser.signalCode === null) {
    const exited = new Promise(resolve => browser.once('exit', resolve));
    try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
    const kill = setTimeout(() => { try { process.kill(-browser.pid, 'SIGKILL'); } catch {} }, 2000);
    await exited; clearTimeout(kill);
  }
  server.close(); await rm(profile, {recursive: true, force: true});
}
