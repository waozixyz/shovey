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
  await call('Page.addScriptToEvaluateOnNewDocument', {source: `
    window.loadingSamples = [];
    new MutationObserver(() => {
      const progress = document.getElementById('progress');
      if (progress && !progress.hidden && progress.hasAttribute('value') && progress.max === 100) window.loadingSamples.push(progress.value);
    }).observe(document, {childList: true, subtree: true, attributes: true, attributeFilter: ['value', 'hidden', 'max']});
  `});
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await call('Page.reload', {ignoreCache: true});
  await settle('!!document.querySelector(".loading-screen")', value => value);
  assert.equal(await evaluate('getComputedStyle(document.querySelector(".loading-screen")).visibility'), 'visible');
  assert(await evaluate('!document.getElementById("progress").hidden'), 'Loading progress must stay visible');
  assert.equal(await settle('document.querySelector(".loading-mark").naturalWidth', value => value === 1200), 1200);
  assert.equal(await evaluate('document.querySelector("link[rel=canonical]").href'), 'https://shovey.waozi.xyz/');
  assert(await evaluate(`document.querySelector('meta[property="og:image"]').content.includes('https://shovey.waozi.xyz/og.png?v=')`));
  assert(await evaluate('document.querySelector(".loading-art source").srcset.includes("title-portrait.png")'));
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
  assert.equal(await evaluate('document.title'), 'Shovey — Push. Solve. Come home.');
  assert(await evaluate('loadingSamples.some(value => value > 0 && value < 100)'), 'No real download progress was shown');
  const initial = await canvasSignature();
  assert.equal(initial.height, 844);
  // Classic now opens on its title artwork. Enter Play before checking the game bar.
  await call('Input.dispatchMouseEvent', {type: 'mousePressed', x: 195, y: 680, button: 'left', buttons: 1, clickCount: 1});
  await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: 195, y: 680, button: 'left', buttons: 0, clickCount: 1});
  assert.notEqual((await settle('Module.FS.analyzePath("/kryon-apps/shovey/campaign").exists', value => value)), false, 'Play did not open the campaign');
  await delay(500);
  async function pressGameKey(key, code, number) {
    await call('Input.dispatchKeyEvent', {type: 'keyDown', key, code, windowsVirtualKeyCode: number});
    await delay(100);
    await call('Input.dispatchKeyEvent', {type: 'keyUp', key, code, windowsVirtualKeyCode: number});
    await delay(200);
  }
  const readCampaignMoves = () => evaluate('parseInt(Module.FS.readFile("/kryon-apps/shovey/campaign", {encoding: "utf8"}).slice(191, 199), 16)');
  for (let reset = 0; reset < 3; reset++) {
    await pressGameKey('r', 'KeyR', 82);
    assert.equal(await readCampaignMoves(), 0, 'R did not reset the current level');
    await pressGameKey('ArrowLeft', 'ArrowLeft', 37);
    assert(await readCampaignMoves() > 0, 'The game froze after R reset');
    assert.equal(await evaluate('document.querySelector("#zib-controls").textContent'), '', 'Reset caused an app frame failure');
  }
  for (const [width, height, density] of [[320,568,1],[1440,500,1],[844,390,2],[390,844,1]]) {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: density, mobile: width < 900});
    const size = await settle(`(() => {
      const canvas = document.querySelector('canvas'), bounds = canvas.getBoundingClientRect();
      return {width: canvas.width, height: canvas.height, cssWidth: bounds.width, cssHeight: bounds.height};
    })()`, value => value.width === width * density && value.height === height * density);
    assert.equal(size.width, width * density);
    assert.equal(size.height, height * density);
    assert(Math.abs(size.width / size.height - size.cssWidth / size.cssHeight) < .002, 'Resizing stretched the canvas');
    assert.equal(await evaluate('getComputedStyle(document.querySelector("canvas")).objectFit'), 'contain');
    await pressGameKey('r', 'KeyR', 82);
    assert.equal(await readCampaignMoves(), 0, 'Reset failed after resizing');
    assert.equal(await evaluate('document.querySelector("#zib-controls").textContent'), '', 'Resizing caused an app frame failure');
  }
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
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await delay(500);
  async function click(x, y) {
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1});
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1});
    await delay(350);
  }
  const campaignBeforeEditor = await evaluate('Module.FS.readFile("/kryon-apps/shovey/campaign", {encoding: "utf8"})');
  await click(60, 34); // Levels -> title.
  await click(356, 422); // Existing Editor title page.
  await delay(650);
  await writeFile(join(shots, 'editor-title.png'), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
  await click(195, 680);
  await writeFile(join(shots, 'editor-home.png'), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
  await click(195, 210); // Classic edition.
  await click(103, 124); // New custom level.
  assert(await settle('Module.FS.analyzePath("/kryon-apps/shovey/editor/classic-1").exists', value => value), 'The browser editor did not create its own saved level');
  await writeFile(join(shots, 'editor-before-name.png'), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
  await click(130, 624); // Name field below the board.
  for (const character of 'Browser Garden') {
    const code = character === ' ' ? 'Space' : 'Key' + character.toUpperCase();
    const number = character.toUpperCase().charCodeAt(0);
    await call('Input.dispatchKeyEvent', {type: 'keyDown', code, key: character, text: character, windowsVirtualKeyCode: number});
    await delay(30);
    await call('Input.dispatchKeyEvent', {type: 'keyUp', code, key: character, windowsVirtualKeyCode: number});
  }
  await delay(250);
  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
  assert(await settle('Module.FS.readFile("/kryon-apps/shovey/editor/classic-levels", {encoding: "utf8"}).includes("Browser Garden")', value => value), 'The browser editor did not save a typed level name');
  await writeFile(join(shots, 'editor-custom-level.png'), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
  const editing = await canvasSignature();
  await click(334, 26); // Play the custom puzzle.
  assert.notEqual((await canvasSignature()).sum, editing.sum, 'The custom level did not enter Play');
  await writeFile(join(shots, 'editor-play.png'), Buffer.from((await call('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40});
  await delay(120);
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40});
  assert.equal(await evaluate('Module.FS.readFile("/kryon-apps/shovey/campaign", {encoding: "utf8"})'), campaignBeforeEditor, 'The editor changed the Classic campaign save');
  await delay(3500); // The host flushes browser storage automatically.
  await call('Page.reload', {ignoreCache: true});
  assert(await settle('document.querySelector("#loading-screen")?.classList.contains("is-hidden")', value => value), 'The game did not reopen after saving an editor level');
  assert(await evaluate('Module.FS.readFile("/kryon-apps/shovey/editor/classic-levels", {encoding: "utf8"}).includes("Browser Garden")'), 'Reloading lost the browser editor level');
  assert.equal(await evaluate('Module.FS.readFile("/kryon-apps/shovey/campaign", {encoding: "utf8"})'), campaignBeforeEditor);
  assert.equal(await evaluate('document.title'), 'Shovey — Push. Solve. Come home.');
  assert.equal(await evaluate('document.querySelector("#zib-controls").textContent'), '', 'The game host reported an editor error');
  await writeFile(join(shots, 'receipt.json'), JSON.stringify({url: target, ...metadata, loading: 'passed', controls: 'passed', orientation: 'passed', progress: 'passed', title: 'passed', editor: 'passed', editor_persistence: 'passed', reset: 'passed', responsive: 'passed'}) + '\n');
  console.log('Web loading and orientation shell passed: ' + target);
} catch (error) {
  try {
    if (socket?.readyState === WebSocket.OPEN) {
      let id = 900000;
      const probe = expression => new Promise(resolve => {
        const requestId = ++id;
        const listener = event => {
          const reply = JSON.parse(event.data);
          if (reply.id !== requestId) return;
          socket.removeEventListener('message', listener);
          resolve(reply.result?.result?.value);
        };
        socket.addEventListener('message', listener);
        socket.send(JSON.stringify({id: requestId, method: 'Runtime.evaluate', params: {expression, returnByValue: true}}));
        setTimeout(() => resolve('probe timed out'), 3000).unref();
      });
      const state = await probe(`(() => {
        const fs = window.Module?.FS;
        const listing = path => { try { return fs.readdir(path); } catch { return []; } };
        const canvas = document.querySelector('canvas');
        const colors = new Set();
        if (canvas?.width) {
          const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
          for (let at = 0; at < pixels.length; at += 388) colors.add((pixels[at] << 16) | (pixels[at + 1] << 8) | pixels[at + 2]);
        }
        return {status: document.querySelector('#status')?.textContent, host: document.querySelector('#zib-controls')?.textContent,
          result: document.querySelector('#result')?.textContent, appFiles: listing('/kryon-apps'),
          shoveyFiles: listing('/kryon-apps/shovey'), colors: colors.size, canvas: [canvas?.width, canvas?.height]};
      })()`);
      await writeFile(join(shots, 'failure.json'), JSON.stringify({state, diagnostics, browserErrors}));
      console.error('Browser failure state: ' + JSON.stringify(state));
    }
  } catch (probeError) { console.error('Could not record browser failure: ' + probeError.message); }
  throw error;
} finally {
  socket?.close();
  try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
  await new Promise(resolve => browser.exitCode !== null || browser.signalCode !== null ? resolve() : browser.once('exit', resolve));
  if (server.listening) await new Promise(resolve => server.close(resolve));
  await rm(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
}
