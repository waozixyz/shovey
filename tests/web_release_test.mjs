// shovey.waozi.xyz as published: the released Shovey in Arcade's browser
// host, built by scripts/build-site.py. Opens level 1 by its controls through
// Kryon's test driver, walks, and requires that the player, its Apps
// controller, the Profile and the game all ran as the page's linked code,
// never on the portable VM. No pixel captures.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {driverSetup} from './web_driver.mjs';

const root = process.argv[2] || new URL('../build/web-site/', import.meta.url).pathname;
const profile = await mkdtemp(join(tmpdir(), 'shovey-release-'));
const types = {'.wasm': 'application/wasm', '.js': 'text/javascript', '.png': 'image/png', '.json': 'application/json'};
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, 'http://localhost');
    const path = decodeURIComponent(url.pathname);
    if (path.includes('..')) throw Error('Invalid path');
    // A browser may still hold an older runtime under its plain URL for
    // hours; the page must ask for its own build's revision.
    if (path === '/runtime.js' && !url.searchParams.has('v')) {
      response.writeHead(200, {'Content-Type': 'text/javascript', 'Cache-Control': 'public, max-age=14400'});
      response.end('console.error("Stale cached Shovey runtime"); Module.onAbort();');
      return;
    }
    const body = await readFile(join(root, path === '/' ? 'index.html' : path));
    response.setHeader('Content-Type', types[path.slice(path.lastIndexOf('.'))] || 'text/html');
    response.end(body);
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const environment = {...process.env};
for (const key of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY']) delete environment[key];
const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], {detached: true, env: environment, stdio: ['ignore', 'ignore', 'pipe']});
let errors = '', socket, sequence = 0;
browser.stderr.on('data', value => errors = (errors + value).slice(-3000));
const lines = [], failures = [];
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
    if (message.method === 'Runtime.exceptionThrown') failures.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (message.method === 'Runtime.consoleAPICalled') lines.push(message.params.args.map(arg => arg.value ?? arg.description ?? '').join(' '));
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
    const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  async function wait(expression) {
    for (let end = Date.now() + 60000; Date.now() < end;) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw Error('Timed out: ' + expression + '; console: ' + lines.slice(-10).join(' | '));
  }
  async function click(x, y) {
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1});
    await delay(100);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1});
    await delay(600);
  }
  let serial = 0;
  async function tree() {
    await evaluate(`Module.FS.writeFile('/tmp/test-driver/command', ${JSON.stringify((++serial) + '\ttree\n')})`);
    await wait(`Module.FS.analyzePath('/tmp/test-driver/reply').exists`);
    const reply = JSON.parse(await evaluate(`Module.FS.readFile('/tmp/test-driver/reply', {encoding: 'utf8'})`));
    await evaluate(`Module.FS.unlink('/tmp/test-driver/reply')`);
    assert(reply.ok, JSON.stringify(reply));
    return reply.nodes;
  }
  async function press(label) {
    const nodes = await tree();
    const row = nodes.find(node => node.label === label && (node.role === 'button' || node.kind === 'button'));
    if (!row) return false;
    await click(row.x + row.width / 2, row.y + row.height / 2);
    return true;
  }
  async function key(code, keyCode) {
    for (const type of ['keyDown', 'keyUp'])
      await call('Input.dispatchKeyEvent', {type, key: code, code, windowsVirtualKeyCode: keyCode});
  }
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.addScriptToEvaluateOnNewDocument', {source: driverSetup});
  await call('Emulation.setDeviceMetricsOverride', {width: 720, height: 1280, deviceScaleFactor: 1, mobile: true});
  await call('Page.navigate', {url: `http://127.0.0.1:${server.address().port}/`});
  await wait(`!!(globalThis.Module && Module.profileReady) || !!document.getElementById('loading')?.classList.contains('error')`);
  assert(!await evaluate(`document.getElementById('loading').classList.contains('error')`), 'The page could not start Shovey');
  const runtime = (await evaluate(`performance.getEntriesByType('resource').map(entry => entry.name)`)).map(name => new URL(name))
    .filter(url => /\/(runtime\.(js|wasm|data)(\.gz)?|arcade\.json|apps\.zx(\.gz)?)$/.test(url.pathname));
  const revisions = new Set(runtime.map(url => url.searchParams.get('v')));
  assert(runtime.some(url => url.pathname === '/runtime.js') && runtime.some(url => url.pathname === '/runtime.wasm') &&
    revisions.size === 1 && /^[0-9a-f]{64}$/.test([...revisions][0]),
  'The runtime files did not share one cache revision: ' + runtime.map(url => url.pathname + url.search).join(' '));
  await wait(`Module.FS.analyzePath('/tmp/test-driver').exists`);
  await delay(1500);
  await press('Not now');
  assert(await press('Play'), 'No Play button: ' + (await tree()).map(node => node.label).join('|'));
  for (let end = Date.now() + 30000; Date.now() < end;) {
    const labels = (await tree()).map(node => node.label);
    if (labels.includes('How do you want to move?')) await press('Swipe and tap');
    else if (labels.some(label => /^Level 1 \//.test(label))) break;
    await delay(250);
  }
  assert((await tree()).some(node => /^Level 1 \//.test(node.label)), 'Level 1 did not open');
  const frames = evaluate(`new Promise(done => { let count = 0, start = performance.now(); function frame(now) { count++; if (now - start < 3000) requestAnimationFrame(frame); else done(count); } requestAnimationFrame(frame); })`);
  for (let step = 0; step < 10; step++) { await key(step % 2 ? 'ArrowLeft' : 'ArrowRight', step % 2 ? 37 : 39); await delay(200); }
  assert(await frames > 30, 'The level stopped drawing while walking');
  const failed = lines.find(line => /frame failed|portable execution failed|cannot run natively/.test(line));
  assert(!failed, failed);
  // Bundles without linked code say so when the VM takes them.
  const vm = lines.filter(line => /which the wasm execution tier does not take/.test(line));
  assert.deepEqual(vm, [], 'Ran on the portable VM instead of linked code');
  assert.deepEqual(failures, []);
  console.log('shovey.waozi.xyz opened level 1 and walked on the release\'s linked code');
} finally {
  try { socket?.close(); } catch {}
  try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
  server.close();
  await rm(profile, {recursive: true, force: true}).catch(() => {});
}
