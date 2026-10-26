// The actual browser game opens its selector at earned progress, including
// after replaying an older puzzle. Scrolling remains free while it is open.
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
  const beforeTip = await evaluate(`Module.FS.readFile('/kryon-apps/shovey/local.campaign', {encoding:'utf8'})`);
  await call('Input.dispatchKeyEvent', {type:'keyDown', key:'ArrowRight', code:'ArrowRight', windowsVirtualKeyCode:39, nativeVirtualKeyCode:39});
  await call('Input.dispatchKeyEvent', {type:'keyUp', key:'ArrowRight', code:'ArrowRight', windowsVirtualKeyCode:39, nativeVirtualKeyCode:39});
  await delay(200);
  assert.equal(await evaluate(`Module.FS.readFile('/kryon-apps/shovey/local.campaign', {encoding:'utf8'})`), beforeTip, 'Movement happened during the introduction');
  await press('Got it');
  await wait(async () => !(await tree()).some(n => n.label === 'Got it'), 'Pip did not dismiss');
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
  for (const [width, height] of [[390, 844], [960, 600]]) {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: true});
    await delay(250);
    await press('Levels');
    await wait(async () => (await tree()).some(n => n.key === 33074 && n.y >= 70 && n.y + n.height <= height), 'Latest unlocked card is not visible');
    await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x: width / 2, y: 250, buttons: 0});
    await delay(100);
    await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x: width / 2, y: 250, deltaX: 0, deltaY: -20000});
    await wait(async () => (await tree()).some(n => n.key === 33001), 'Cannot scroll back to the first level');
    await delay(500);
    assert((await tree()).some(n => n.key === 33001), 'Selector snapped back during manual scrolling');
    await press('1');
    await wait(async () => (await tree()).some(n => n.label.startsWith('Level 1 /')), 'Older level did not open');
    await press('Levels');
    await wait(async () => (await tree()).some(n => n.key === 33074 && n.y >= 70 && n.y + n.height <= height), 'Replaying an older level moved the selector default');
    await press('Continue');
  }
  assert.equal(failures.length, 0, failures.join('|'));
  console.log('Pip artwork, paused input and saved acknowledgement; selector: earned level74 visible by default in portrait/landscape; manual scroll preserved; replaying level1 still opens at74');
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
