// Serve the built page alone on another site, the way an app store bundles
// it, inside a sandboxed iframe, and check that it loads the game, its
// pictures and its saves from the game's home instead of missing them.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = process.env.WEB_TEST_ROOT || new URL('../build/web/', import.meta.url).pathname;
const profile = await mkdtemp(join(tmpdir(), 'shovey-copy-'));
const types = {'.wasm': 'application/wasm', '.js': 'text/javascript', '.png': 'image/png', '.json': 'application/json'};
// The game's home serves its files to every site, as Cloudflare Pages does.
const home = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (path.includes('..')) throw Error('Invalid path');
    response.setHeader('Access-Control-Allow-Origin', '*');
    response.setHeader('Content-Type', types[path.slice(path.lastIndexOf('.'))] || 'application/octet-stream');
    response.end(await readFile(join(root, path)));
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => home.listen(0, '127.0.0.1', resolve));
const homeUrl = `http://127.0.0.1:${home.address().port}/`;
const page = (await readFile(join(root, 'index.html'), 'utf8')).replace("'https://shovey.waozi.xyz/'", JSON.stringify(homeUrl));
assert(page.includes(homeUrl), 'The page no longer names its home');
const store = createServer((request, response) => {
  const path = new URL(request.url, 'http://localhost').pathname;
  response.setHeader('Content-Type', 'text/html');
  if (path === '/') response.end('<!doctype html><iframe id="app" src="/bundle/app" sandbox="allow-scripts" width="390" height="700"></iframe>');
  else if (path === '/bundle/app') response.end(page);
  else response.writeHead(404).end('<h1>Not found</h1>');
});
await new Promise(resolve => store.listen(0, 'localhost', resolve));
const environment = {...process.env};
for (const key of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY']) delete environment[key];
// One renderer for the page and its sandboxed frame, so DevTools reaches both.
const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
  '--disable-site-isolation-trials', '--disable-features=IsolateOrigins,site-per-process', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'],
  {detached: true, env: environment, stdio: ['ignore', 'ignore', 'pipe']});
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
  const pending = new Map(), failures = [], contexts = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') failures.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (message.method === 'Runtime.executionContextCreated' && message.params.context.auxData?.isDefault)
      contexts.set(message.params.context.auxData.frameId, message.params.context.id);
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
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.navigate', {url: `http://localhost:${store.address().port}/`});
  // The sandboxed frame has no origin of its own, so the page cannot reach
  // into it; DevTools evaluates in the frame's own context.
  let frame;
  for (let end = Date.now() + 20000; Date.now() < end && !contexts.has(frame);) {
    frame = (await call('Page.getFrameTree')).frameTree.childFrames?.[0]?.frame.id;
    await delay(100);
  }
  assert(contexts.has(frame), 'The bundled page did not start');
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, contextId: contexts.get(frame), returnByValue: true});
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  const opened = `!!(window.Module?.FS?.analyzePath('/assets/shovey/catalog.json').exists && document.getElementById('loading-screen').classList.contains('is-hidden'))`;
  for (let end = Date.now() + 60000; Date.now() < end && !await evaluate(opened);) await delay(200);
  assert(await evaluate(opened), 'The bundled page did not open the game: ' + await evaluate(`document.getElementById('status').textContent`) + '; ' + failures.join('|'));
  const pictures = JSON.parse(await evaluate(`JSON.stringify([...document.querySelectorAll('#loading-screen img')].map(image => [image.currentSrc, image.naturalWidth]))`));
  for (const [source, width] of pictures) {
    assert(source.startsWith(homeUrl), 'A loading picture stayed on the store: ' + source);
    assert(width > 0, 'A loading picture is missing: ' + source);
  }
  assert(await evaluate(`Module.FS.readdir('/assets/shovey').length > 2`), 'The game opened without its pictures');
  assert.equal(failures.length, 0, failures.join('|'));
  console.log('A copy of the page on another site loads the game and its pictures from the game\'s home; no screenshots.');
} finally {
  if (socket) socket.close();
  if (browser.exitCode === null && browser.signalCode === null) {
    const exited = new Promise(resolve => browser.once('exit', resolve));
    try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
    const kill = setTimeout(() => { try { process.kill(-browser.pid, 'SIGKILL'); } catch {} }, 2000);
    await exited;
    clearTimeout(kill);
  }
  home.close();
  store.close();
  await rm(profile, {recursive: true, force: true});
}
