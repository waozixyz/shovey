// Verify board movement and Pip's tips on a wide browser window: keys move under a tip, the first tap anywhere only dismisses it; no pixel captures.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {driverSetup} from './web_driver.mjs';

const root = process.env.WEB_TEST_ROOT || new URL('../build/web/', import.meta.url).pathname;
const profile = await mkdtemp(join(tmpdir(), 'shovey-tap-'));
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (path.includes('..')) throw Error('Invalid path');
    response.setHeader('Content-Type', path.endsWith('.wasm') ? 'application/wasm' : path.endsWith('.js') ? 'text/javascript' : path.endsWith('.png') ? 'image/png' : 'text/html');
    response.end(await readFile(join(root, path === '/' ? 'index.html' : path)));
  } catch { response.writeHead(404).end(); }
});
if (!process.env.WEB_TEST_URL) await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const target = process.env.WEB_TEST_URL ||
  `http://127.0.0.1:${server.address().port}${process.env.WEB_TEST_PATH || '/index.html'}`;
const environment = {...process.env};
for (const key of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY']) delete environment[key];
const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile, target], {detached: true, env: environment, stdio: ['ignore', 'ignore', 'pipe']});
let errors = '', socket, sequence = 0;
browser.stderr.on('data', value => errors = (errors + value).slice(-3000));
try {
  let port;
  for (let end = Date.now() + 30000; Date.now() < end && !port;) {
    try { port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; }
    catch { assert.equal(browser.exitCode, null, errors); await delay(50); }
  }
  assert(port, 'Chromium did not start: ' + errors);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener('open', resolve, {once: true}));
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
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
  async function wait(expression) {
    for (let end = Date.now() + 45000; Date.now() < end;) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw Error('Timed out: ' + expression);
  }
  async function click(x, y) {
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1});
    await delay(100);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1});
    await delay(400);
  }
  async function key(code, keyCode) {
    for (const type of ['keyDown', 'keyUp'])
      await call('Input.dispatchKeyEvent', {type, key: code, code, windowsVirtualKeyCode: keyCode});
  }
  async function button(label) {
    const node = (await tree()).find(candidate => candidate.label === label &&
      (candidate.role === 'button' || candidate.kind === 'button'));
    assert(node, 'Missing button ' + label);
    await click(node.x + node.width / 2, node.y + node.height / 2);
    return node;
  }
  async function cardIsVisible() {
    return (await tree()).some(node => node.label === 'Got it' && (node.role === 'button' || node.kind === 'button'));
  }
  async function playerCentre() {
    const player = (await tree()).find(node => node.label === 'Shovey' && node.role === 'image');
    assert(player, 'Missing Shovey in the widget tree');
    return [player.x + player.width / 2, player.y + player.height / 2];
  }
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.addScriptToEvaluateOnNewDocument', {source: driverSetup});
  const width = Number(process.env.WEB_TEST_WIDTH || 1280);
  const height = Number(process.env.WEB_TEST_HEIGHT || 720);
  await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
  await call('Page.reload');
  await wait(`typeof Module !== 'undefined' && Module.FS?.analyzePath('/tmp/test-driver').exists && document.querySelector('#loading-screen').classList.contains('is-hidden')`);
  await delay(600);
  let serial = 0;
  async function tree() {
    await evaluate(`Module.FS.writeFile('/tmp/test-driver/command', ${JSON.stringify((++serial) + '\ttree\n')})`);
    await wait(`Module.FS.analyzePath('/tmp/test-driver/reply').exists`);
    const reply = JSON.parse(await evaluate(`Module.FS.readFile('/tmp/test-driver/reply', {encoding: 'utf8'})`));
    await evaluate(`Module.FS.unlink('/tmp/test-driver/reply')`);
    assert(reply.ok, JSON.stringify(reply));
    return reply.nodes;
  }
  const opening = await tree();
  const labels = opening.map(node => node.label).filter(Boolean);
  for (const forbidden of ['Profile', 'Dew', 'Sign in', 'Buy', 'Fullscreen', 'Waozi', 'itch.io'])
    assert(!labels.some(label => label.toLowerCase().includes(forbidden.toLowerCase())),
      `${forbidden} appeared in the web UI: ${labels.join('|')}`);
  const play = opening.find(node => node.label === 'Play' && (node.role === 'button' || node.kind === 'button'));
  assert(play, 'Missing Play on the title screen');
  await click(play.x + play.width / 2, play.y + play.height / 2);
  await wait(`Module.FS.analyzePath('/kryon-apps/shovey/local.campaign').exists`);
  await delay(600);
  // The first level asks how to move; this test plays with swipe and tap.
  const choice = (await tree()).find(node => node.label === 'Swipe and tap');
  assert(choice, 'The first level did not ask how to move');
  await click(choice.x + choice.width / 2, choice.y + choice.height / 2);
  await delay(600);
  assert(!(await tree()).find(node => node.label === 'How do you want to move?'), 'The controls question stayed open');
  // Pip's introduction: keys still move Shovey under it.
  assert(await cardIsVisible(), 'The first level did not show Pip');
  const campaign = () => evaluate(`Module.FS.readFile('/kryon-apps/shovey/local.campaign', {encoding: 'utf8'})`);
  async function moveUntilPlayerMoved(actions) {
    const [beforeX, beforeY] = await playerCentre();
    for (const action of actions) {
      await action();
      for (let attempt = 0; attempt < 8; attempt++) {
        const [afterX, afterY] = await playerCentre();
        if (Math.abs(afterX - beforeX) + Math.abs(afterY - beforeY) > 2) return;
        await delay(100);
      }
    }
    throw Error('No tested movement moved Shovey');
  }
  async function swipe(dx, dy) {
    const board = (await tree()).find(node => node.key === 22000);
    assert(board, 'Missing the board in the widget tree');
    const x = board.x + board.width / 2;
    const y = board.y + board.height / 2;
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1});
    await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x: x + dx, y: y + dy, button: 'left', buttons: 1});
    await delay(100);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: x + dx, y: y + dy, button: 'left', buttons: 0, clickCount: 1});
    await delay(400);
  }
  const arrows = [
    ['ArrowLeft', 37], ['ArrowUp', 38], ['ArrowRight', 39], ['ArrowDown', 40]
  ];
  await moveUntilPlayerMoved(arrows.map(([code, keyCode]) => () => key(code, keyCode)));
  assert(await cardIsVisible(), 'Keyboard movement dismissed Pip');
  async function dismissWithoutMoving(action, name) {
    const before = await campaign();
    const [beforeX, beforeY] = await playerCentre();
    await action();
    await delay(500);
    assert(!(await cardIsVisible()), name + ' did not dismiss Pip');
    assert.equal(await campaign(), before, name + ' dismissal stepped the board');
    const [afterX, afterY] = await playerCentre();
    assert(Math.abs(afterX - beforeX) + Math.abs(afterY - beforeY) <= 2, name + ' dismissal moved Shovey');
  }
  async function replayPip() {
    await button('Help');
    await button('Pip’s tips');
    assert(await cardIsVisible(), 'Replaying Pip from Help did not show him');
  }
  // The first tap or swipe anywhere, beside the board or on it, only
  // continues Pip's guide.
  await dismissWithoutMoving(() => click(12, height / 2), 'A tap beside the board');
  await replayPip();
  const board = (await tree()).find(node => node.key === 22000);
  assert(board, 'Missing the board in the widget tree');
  await dismissWithoutMoving(() => click(board.x + board.width / 2, board.y + board.height / 2), 'A tap on the board');
  await replayPip();
  await dismissWithoutMoving(() => swipe(100, 0), 'A swipe');
  await replayPip();
  await dismissWithoutMoving(() => button('Got it'), 'The button');
  await replayPip();
  await dismissWithoutMoving(() => key('Enter', 13), 'Enter');
  await replayPip();
  await dismissWithoutMoving(() => key('Escape', 27), 'Escape');
  // Without Pip, taps, swipes and the pad move Shovey again.
  await moveUntilPlayerMoved([12, width - 12].map(x => () => click(x, height / 2)));
  await moveUntilPlayerMoved([
    () => swipe(-100, 0), () => swipe(0, -100), () => swipe(100, 0), () => swipe(0, 100)
  ]);
  await button('Help');
  await button('Movement pad');
  await button('Close help');
  const pad = (await tree()).find(node => node.key === 20040);
  assert(pad, 'The movement pad did not appear');
  const third = pad.width / 3;
  const arms = [
    [pad.x + third / 2, pad.y + third * 1.5],
    [pad.x + third * 1.5, pad.y + third / 2],
    [pad.x + third * 2.5, pad.y + third * 1.5],
    [pad.x + third * 1.5, pad.y + third * 2.5]
  ];
  await moveUntilPlayerMoved(arms.map(([x, y]) => () => click(x, y)));
  const saved = await campaign();
  await call('Page.reload');
  await wait(`typeof Module !== 'undefined' && Module.FS?.analyzePath('/tmp/test-driver').exists &&
    Module.FS.analyzePath('/kryon-apps/shovey/local.campaign').exists &&
    document.querySelector('#loading-screen').classList.contains('is-hidden')`);
  assert.equal(await campaign(), saved, 'The local campaign save did not survive a reload');
  console.log(`PASS: Shovey web ${width}x${height}: keys move under Pip, the first tap or swipe only dismisses him, then taps, swipes and the pad move Shovey`);
} finally {
  socket?.close();
  if (browser.exitCode === null && browser.signalCode === null) {
    const exited = new Promise(resolve => browser.once('exit', resolve));
    try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
    const kill = setTimeout(() => { try { process.kill(-browser.pid, 'SIGKILL'); } catch {} }, 2000);
    await exited;
    clearTimeout(kill);
  }
  server.close();
  await rm(profile, {recursive: true, force: true});
}
