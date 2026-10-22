// Runs the built standalone web shell in a private Chromium and loopback server.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = new URL('../build/web/', import.meta.url).pathname;
const shots = new URL('../build/web-test/', import.meta.url).pathname;
await mkdir(shots, {recursive: true});
const profile = await mkdtemp(join(shots, 'browser-profile-'));
const server = createServer(async (request, response) => {
  try {
    const name = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (name.includes('..')) throw new Error('invalid path');
    const bytes = await readFile(join(root, name));
    response.setHeader('Content-Type', name.endsWith('.wasm') ? 'application/wasm'
      : name.endsWith('.js') ? 'text/javascript'
      : name.endsWith('.png') ? 'image/png' : 'text/html');
    response.end(bytes);
  } catch {
    response.writeHead(404).end();
  }
});
if (!process.env.WEB_TEST_URL) await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const target = process.env.WEB_TEST_URL || 'http://127.0.0.1:' + server.address().port + '/index.html';
const metadata = await (await fetch(new URL('build.json', target), {cache: 'no-store'})).json();
assert(metadata.classic_levels >= 30, 'The approved campaign is missing');
if (process.env.WEB_TEST_REVISION) assert.equal(metadata.revision, process.env.WEB_TEST_REVISION);
const browserEnvironment = {...process.env};
for (const name of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY']) delete browserEnvironment[name];
const browser = spawn(process.env.CHROMIUM || 'chromium', [
  '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
  '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
  '--user-data-dir=' + profile,
  target
], {detached: true, env: browserEnvironment, stdio: ['ignore', 'ignore', 'pipe']});

let browserErrors = '';
let socket;
let diagnostics = '';
browser.stderr.on('data', value => browserErrors = (browserErrors + value).slice(-4000));
try {
  let port;
  for (let attempts = 0; attempts < 300; attempts++) {
    try {
      port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0];
      break;
    } catch {
      assert.equal(browser.exitCode, null, 'Chromium exited: ' + browserErrors);
      await delay(50);
    }
  }
  assert(port, 'Chromium debug endpoint unavailable: ' + browserErrors);
  const pages = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', reject, {once: true});
  });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.consoleAPICalled') {
      diagnostics += message.params.args.map(value => value.value || value.description || '').join(' ') + '\n';
    }
    if (message.method === 'Runtime.exceptionThrown') diagnostics += JSON.stringify(message.params) + '\n';
    if (pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  });
  async function call(method, params = {}) {
    const id = ++sequence;
    const reply = new Promise((resolve, reject) => {
      pending.set(id, resolve);
      setTimeout(() => {
        if (pending.delete(id)) reject(new Error(method + ' timed out: ' + diagnostics));
      }, 15000).unref();
    });
    socket.send(JSON.stringify({id, method, params}));
    const result = await reply;
    assert(!result.error, JSON.stringify(result));
    return result.result;
  }
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, returnByValue: true});
    assert(!result.exceptionDetails, JSON.stringify(result));
    return result.result.value;
  }
  async function settle(expression, accept) {
    const deadline = Date.now() + 30000;
    for (;;) {
      const value = await evaluate(expression);
      if (accept(value) || Date.now() > deadline) return value;
      await delay(100);
    }
  }
  async function canvasSignature() {
    return evaluate(`(() => {
      const canvas = document.querySelector('canvas');
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      let sum = 0;
      for (let index = 0; index < pixels.length; index += 97 * 4) {
        sum = (sum + pixels[index] * 31 + pixels[index + 1] * 17 + pixels[index + 2] * 13) % 0x7fffffff;
      }
      return {height: canvas.height, ink: pixels.length, sum};
    })()`);
  }

  await call('Runtime.enable');
  await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await call('Page.reload', {ignoreCache: true});
  await settle('!!document.querySelector(".loading-screen")', value => value);
  assert.equal(await evaluate('getComputedStyle(document.querySelector(".loading-screen")).visibility'), 'visible');
  assert.equal(await settle('document.querySelector(".loading-mark").naturalWidth', value => value === 480), 480);
  await settle('document.querySelector("#loading-screen").classList.contains("is-hidden")', value => value);
  await settle('Number(getComputedStyle(document.querySelector(".loading-screen")).opacity)', value => value === 0);
  await delay(100);
  assert(!/ABORT|RuntimeError|Could not (start|download)/.test(diagnostics), diagnostics + browserErrors);
  // A fully drawn title screen may be still by the time loading hides.
  // Verify its mounted bundle and rendered image instead of requiring motion.
  const ready = await settle(`(() => {
    if (!Module.FS?.analyzePath('/kryon-apps/shovey/assets/shovey/catalog.json').exists) return false;
    const canvas = document.querySelector('canvas');
    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    const colors = new Set();
    for (let at = 0; at < pixels.length; at += 97 * 4) colors.add((pixels[at] << 16) | (pixels[at + 1] << 8) | pixels[at + 2]);
    return colors.size > 64;
  })()`, value => value);
  assert(ready, 'The game bundle or title artwork did not render');
  const initial = await canvasSignature();
  assert.equal(initial.height, 844);
  // Classic now opens on its title artwork. Enter Play before checking the game bar.
  await call('Input.dispatchMouseEvent', {type: 'mousePressed', x: 195, y: 680, button: 'left', buttons: 1, clickCount: 1});
  await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: 195, y: 680, button: 'left', buttons: 0, clickCount: 1});
  assert.notEqual((await settle('Module.FS.analyzePath("/kryon-apps/shovey/campaign").exists', value => value)), false, 'Play did not open the campaign');
  await delay(500);
  const beforeMuteShot = (await call('Page.captureScreenshot', {format: 'png'})).data;

  await evaluate(`(() => {
    const canvas = document.querySelector('canvas');
    for (const type of ['mousedown', 'mouseup', 'click']) {
      canvas.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, clientX: 360, clientY: 26, button: 0, buttons: type === 'mousedown' ? 1 : 0}));
    }
  })()`);
  await delay(2000);
  const afterMuteShot = (await call('Page.captureScreenshot', {format: 'png'})).data;
  await writeFile(join(shots, 'before-mute.png'), Buffer.from(beforeMuteShot, 'base64'));
  await writeFile(join(shots, 'after-mute.png'), Buffer.from(afterMuteShot, 'base64'));
  if (afterMuteShot === beforeMuteShot) {
    await writeFile(join(shots, 'diagnostics.json'), JSON.stringify({diagnostics, browserErrors, state: await evaluate(`({status: document.querySelector('#status').textContent, result: document.querySelector('#result').textContent, aborted: typeof ABORT !== 'undefined' && ABORT, files: typeof FS !== 'undefined' ? FS.readdir('/tmp/kryon-zib') : []})`)}));
  }
  assert(afterMuteShot !== beforeMuteShot, 'Mute button did not redraw: ' + diagnostics);

  await evaluate(`(() => {
    const canvas = document.querySelector('canvas');
    for (const type of ['mousedown', 'mouseup', 'click']) {
      canvas.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, clientX: 114, clientY: 26, button: 0, buttons: type === 'mousedown' ? 1 : 0}));
    }
  })()`);
  await delay(500);
  const portraitSelector = await canvasSignature();
  assert.notEqual(portraitSelector.sum, initial.sum, 'Levels selector did not redraw: ' + diagnostics + browserErrors);

  await call('Emulation.setDeviceMetricsOverride', {width: 844, height: 390, deviceScaleFactor: 1, mobile: true});
  await delay(500);
  const landscapeSelector = await canvasSignature();
  assert.equal(landscapeSelector.height, 390);
  assert.notEqual(landscapeSelector.sum, portraitSelector.sum, 'Landscape selector reused the portrait layout');
  assert(!/ABORT|RuntimeError|Could not (start|download)/.test(diagnostics), diagnostics + browserErrors);

  const screenshot = await call('Page.captureScreenshot', {format: 'png'});
  await writeFile(join(shots, 'landscape-selector.png'), Buffer.from(screenshot.data, 'base64'));
  await writeFile(join(shots, 'receipt.json'), JSON.stringify({url: target, ...metadata, loading: 'passed', controls: 'passed', orientation: 'passed'}) + '\n');
  console.log('Web loading and orientation shell passed: ' + target);
} finally {
  socket?.close();
  try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
  await new Promise(resolve => browser.exitCode !== null || browser.signalCode !== null ? resolve() : browser.once('exit', resolve));
  if (server.listening) await new Promise(resolve => server.close(resolve));
  await rm(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
}
