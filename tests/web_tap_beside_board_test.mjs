// Verify that pressing the empty space beside the board steps the player, on a wide browser window; no pixel captures.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = new URL('../build/web/', import.meta.url).pathname;
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
const target = process.env.WEB_TEST_URL || `http://127.0.0.1:${server.address().port}/index.html`;
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
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.addScriptToEvaluateOnNewDocument', {source: `
    document.addEventListener('DOMContentLoaded', () => {
      Module.preRun = Module.preRun || [];
      Module.preRun.push(function() {
        ENV.KRYON_TEST_DRIVER = '/tmp/test-driver';
        Module.FS.mkdirTree('/tmp/test-driver');
      });
    }, {once:true});
  `});
  const width = 1280, height = 720;
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
  const play = (await tree()).find(node => node.label === 'Play' && (node.role === 'button' || node.kind === 'button'));
  assert(play, 'Missing Play on the title screen');
  await click(play.x + play.width / 2, play.y + play.height / 2);
  await wait(`Module.FS.analyzePath('/kryon-apps/shovey/campaign').exists`);
  await delay(600);
  const campaign = () => evaluate(`Module.FS.readFile('/kryon-apps/shovey/campaign', {encoding: 'utf8'})`);
  const before = await campaign();
  // The board is centred, so the window's far edges lie beside it. A wall may
  // block one side; the player walks towards at least one of them.
  let moved = false;
  for (const x of [12, width - 12]) {
    await click(x, height / 2);
    await delay(400);
    if (await campaign() !== before) { moved = true; break; }
  }
  assert(moved, 'Pressing beside the board did not step the player');
  console.log(`PASS: Shovey web ${width}x${height}: pressing beside the board steps the player`);
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
