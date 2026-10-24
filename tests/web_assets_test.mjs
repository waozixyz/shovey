// Every picture the web game shows must be in the files it packs. Opens the
// game in landscape, portrait and as a small embed, plays into a level and
// opens the level list, and checks each image on screen: its file exists in
// the game's file system and starts as a PNG. A wrong asset folder shows as
// "Missing image" or tile names instead of sprites, as it once did in
// landscape. WEB_TEST_URL checks a deployed site instead of build/web.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = process.env.WEB_TEST_ROOT || new URL('../build/web/', import.meta.url).pathname;
const profile = await mkdtemp(join(tmpdir(), 'shovey-assets-'));
const driver = `document.addEventListener('DOMContentLoaded', () => {
  Module.preRun = Module.preRun || [];
  Module.preRun.push(function() { ENV.KRYON_TEST_DRIVER = '/tmp/test-driver'; Module.FS.mkdirTree('/tmp/test-driver'); });
}, {once:true});`;
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (path.includes('..')) throw Error('Invalid path');
    response.setHeader('Content-Type', path.endsWith('.wasm') ? 'application/wasm' : path.endsWith('.js') ? 'text/javascript' :
      path.endsWith('.png') ? 'image/png' : path === '/' || path.endsWith('.html') ? 'text/html' : 'application/octet-stream');
    response.end(await readFile(join(root, path === '/' ? 'index.html' : path)));
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const site = process.env.WEB_TEST_URL || `http://127.0.0.1:${server.address().port}/`;
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
  assert(port, 'Chromium did not start: ' + errors);
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
  async function wait(expression, timeout = 60000) {
    for (let end = Date.now() + timeout; Date.now() < end;) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw Error('Timed out: ' + expression + '; errors: ' + failures.join('|'));
  }
  let serial = 0;
  async function command(line) {
    const text = (++serial) + '\t' + line + '\n';
    await evaluate(`Module.FS.writeFile('/tmp/test-driver/command.new', ${JSON.stringify(text)}); Module.FS.rename('/tmp/test-driver/command.new', '/tmp/test-driver/command')`);
    await wait(`Module.FS.analyzePath('/tmp/test-driver/reply').exists`);
    const reply = JSON.parse(await evaluate(`Module.FS.readFile('/tmp/test-driver/reply', {encoding: 'utf8'})`));
    await evaluate(`Module.FS.unlink('/tmp/test-driver/reply')`);
    return reply;
  }
  async function settle() {
    for (let end = Date.now() + 20000; Date.now() < end;) {
      if ((await command('status')).stable_frames >= 10) return;
      await delay(100);
    }
  }
  async function press(label) {
    const reply = await command('press\tlabel=' + label + '\tvisible=1');
    if (reply.ok) await settle();
    return reply.ok;
  }
  // Every image on screen: its file must exist and be a PNG.
  async function check(view) {
    const nodes = (await command('tree')).nodes.filter(node => node.kind === 'image' && node.visible && node.detail);
    assert(nodes.length > 0, view + ': no images on screen');
    const paths = [...new Set(nodes.map(node => node.detail))];
    const bad = await evaluate(`JSON.stringify(${JSON.stringify(paths)}.filter(path => {
      const file = path.startsWith('/') ? path : '/' + path;
      if (!Module.FS.analyzePath(file).exists) return true;
      const head = Module.FS.readFile(file).subarray(0, 8);
      return !(head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47);
    }))`);
    assert.deepEqual(JSON.parse(bad), [], view + ': images missing from the packed files');
    return paths.length;
  }
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.addScriptToEvaluateOnNewDocument', {source: driver});
  const views = [
    ['landscape', 1280, 800, ''], ['portrait', 420, 860, ''],
    ['landscape embed', 480, 400, '?mini'], ['portrait embed', 390, 700, '?mini']];
  const counts = [];
  for (const [view, width, height, query] of views) {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: width < 600});
    await call('Page.navigate', {url: site + 'index.html' + query});
    await wait(`globalThis.Module?.FS?.analyzePath('/assets/shovey/catalog.json').exists && document.querySelector('#loading-screen')?.classList.contains('is-hidden')`);
    await settle();
    if (!query) assert(await press('Play'), view + ': no Play button');
    // A first game asks how to move; either answer shows the board.
    if (!(await press('Movement pad'))) await settle();
    const board = await check(view + ' board');
    assert(board >= 4, view + ': the board shows only ' + board + ' pictures');
    let list = 0;
    if (await press('Levels')) list = await check(view + ' level list');
    counts.push(`${view} ${board}${list ? '+' + list : ''}`);
  }
  assert.equal(failures.length, 0, failures.join('|'));
  console.log(`Web assets: every picture on screen is packed and a PNG (${counts.join(', ')} files); no screenshots.`);
} finally {
  if (socket) socket.close();
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
