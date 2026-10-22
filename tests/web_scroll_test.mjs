// Exercise Shovey's level selector in its real web shell, with a private profile.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = new URL('../build/web/', import.meta.url).pathname;
const profile = await mkdtemp(join(tmpdir(), 'shovey-scroll-'));
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
const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile, target], {env: environment, stdio: ['ignore', 'ignore', 'pipe']});
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
  async function signature(header = false) {
    return evaluate(`(() => {
      const c = document.querySelector('canvas');
      const p = c.getContext('2d').getImageData(16, ${header ? '0' : '72'}, c.width - 48, ${header ? '64' : 'c.height - 88'}).data;
      let hash = 2166136261;
      for (let at = 0; at < p.length; at += 4) hash = Math.imul(hash ^ (p[at] << 16 | p[at + 1] << 8 | p[at + 2]), 16777619) >>> 0;
      return hash;
    })()`);
  }
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await call('Page.reload');
  await wait(`typeof Module !== 'undefined' && Module.FS?.analyzePath('/kryon-apps/shovey/assets/shovey/catalog.json').exists && document.querySelector('#loading-screen').classList.contains('is-hidden')`);
  await delay(600);
  await click(195, 680);
  await wait(`Module.FS.analyzePath('/kryon-apps/shovey/campaign').exists`);
  await evaluate(`(() => {
    globalThis.levelPreviewReads = [];
    const open = Module.FS.open;
    Module.FS.open = function(path, ...args) {
      if (typeof path === 'string' && path.includes('/levels/')) levelPreviewReads.push(path);
      return open.call(this, path, ...args);
    };
  })()`);
  await click(114, 26);
  await wait(`levelPreviewReads.some(path => path.endsWith('/levels/1.png'))`);
  const campaign = await evaluate(`Module.FS.readFile('/kryon-apps/shovey/campaign', {encoding: 'utf8'})`);
  for (const [width, height] of [[390, 844], [844, 390]]) {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: true});
    await delay(600);
    const x = width / 2, y = height / 2;
    await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x, y});
    await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x, y, deltaX: 0, deltaY: -12000});
    await delay(700);
    const top = await signature(), header = await signature(true);
    const shots = new URL('../build/web-scroll-test/', import.meta.url).pathname;
    await mkdir(shots, {recursive: true});
    await writeFile(join(shots, `${width}-top.png`), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
    await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x, y, deltaX: 0, deltaY: 12000});
    await delay(700);
    await writeFile(join(shots, `${width}-bottom.png`), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
    assert.notEqual(await signature(), top, 'Wheel did not scroll the level list');
    assert.equal(await signature(true), header, 'Level navigation moved with the list');
    await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x, y, deltaX: 0, deltaY: -12000});
    await delay(700);
    await writeFile(join(shots, `${width}-returned.png`), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
    assert.equal(await signature(), top, 'Cannot scroll back to the first row');
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', x: width - 21, y: 84, button: 'left', buttons: 1, clickCount: 1});
    await delay(100);
    await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x: width - 21, y: height - 28, buttons: 1});
    await delay(100);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: width - 21, y: height - 28, button: 'left', buttons: 0, clickCount: 1});
    await delay(400);
    assert.notEqual(await signature(), top, 'Dragging the scrollbar did not scroll levels');
    assert.equal(await evaluate(`Module.FS.readFile('/kryon-apps/shovey/campaign', {encoding: 'utf8'})`), campaign, 'Browsing levels changed the saved game');
    console.log(`PASS: Shovey web ${width}x${height}: wheel, scrollbar, fixed header, retained game`);
  }
} finally {
  socket?.close();
  browser.kill('SIGTERM');
  await new Promise(resolve => browser.exitCode !== null ? resolve() : browser.once('exit', resolve));
  server.close();
  await rm(profile, {recursive: true, force: true});
}
