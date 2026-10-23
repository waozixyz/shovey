// The web game loads its approved levels from the node's live campaign:
// more levels after an approval, kept offline, and refused unless every
// level's own route wins. The node is replaced by the test; no screenshots.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = process.env.WEB_TEST_ROOT || new URL('../build/web/', import.meta.url).pathname;
const approved = JSON.parse(await readFile(process.env.WEB_TEST_CAMPAIGN || new URL('../levels/approved.json', import.meta.url), 'utf8'));
const builtIn = approved.levels.length;
// A campaign one level longer than this build, as the node would serve after
// an approval; its new last level repeats level 1 with that level's route.
const longer = structuredClone(approved);
longer.levels.push({...structuredClone(approved.levels[0]), number: builtIn + 1});
// The same campaign with a route that does not win must be refused.
const broken = structuredClone(longer);
broken.levels[builtIn].solution = '0';
const profile = await mkdtemp(join(tmpdir(), 'shovey-live-'));
const driver = `document.addEventListener('DOMContentLoaded', () => {
  Module.preRun = Module.preRun || [];
  Module.preRun.push(function() { ENV.KRYON_TEST_DRIVER = '/tmp/test-driver'; Module.FS.mkdirTree('/tmp/test-driver'); });
}, {once:true});`;
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (path.includes('..')) throw Error('Invalid path');
    if (path === '/' || path === '/index.html') {
      const page = (await readFile(join(root, 'index.html'), 'utf8')).replace('<head>', `<head><script>${driver}</script>`);
      response.setHeader('Content-Type', 'text/html'); response.end(page); return;
    }
    response.setHeader('Content-Type', path.endsWith('.wasm') ? 'application/wasm' : path.endsWith('.js') ? 'text/javascript' : path.endsWith('.png') ? 'image/png' : 'application/octet-stream');
    response.end(await readFile(join(root, path)));
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const target = `http://127.0.0.1:${server.address().port}/index.html`;
const environment = {...process.env};
for (const key of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY']) delete environment[key];
const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], {detached: true, env: environment, stdio: ['ignore', 'ignore', 'pipe']});
let errors = '', socket, sequence = 0, serving = longer, served = 0;
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
  // The node is replaced by this test: it answers the campaign publication
  // with whatever `serving` holds, or fails when it is null.
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') failures.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (message.method === 'Fetch.requestPaused') {
      const {requestId, request} = message.params;
      served += 1;
      if (!serving) { call('Fetch.failRequest', {requestId, errorReason: 'ConnectionRefused'}); return; }
      const body = JSON.stringify({publication: {id: request.url.split('/').pop(), format: 'shovey-campaign-1', title: 'Shovey Classic',
        levels: serving.levels.length, visibility: 'public'}, document: serving});
      call('Fetch.fulfillRequest', {requestId, responseCode: 200, body: Buffer.from(body).toString('base64'),
        responseHeaders: [{name: 'Content-Type', value: 'application/json'}, {name: 'Access-Control-Allow-Origin', value: '*'}]});
    }
    if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
  });
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
  async function labels() {
    const command = (++serial) + '\ttree\n';
    await evaluate(`Module.FS.writeFile('/tmp/test-driver/command', ${JSON.stringify(command)})`);
    await wait(`Module.FS.analyzePath('/tmp/test-driver/reply').exists`);
    const reply = JSON.parse(await evaluate(`Module.FS.readFile('/tmp/test-driver/reply', {encoding: 'utf8'})`));
    await evaluate(`Module.FS.unlink('/tmp/test-driver/reply')`);
    assert(reply.ok, JSON.stringify(reply));
    return reply.nodes.map(node => node.label);
  }
  async function count(expected) {
    for (let end = Date.now() + 30000; Date.now() < end;) {
      const header = (await labels()).find(label => /^Level \d+ \/ \d+$/.test(label));
      if (header && header.endsWith('/ ' + expected)) return;
      await delay(250);
    }
    const files = await evaluate(`JSON.stringify(Module.FS.readdir('/kryon-apps/shovey').filter(name => name.startsWith('live')))`);
    throw Error('The game never showed ' + expected + ' levels: ' + (await labels()).filter(label => label.startsWith('Level')).join('|') + '; served ' + served + '; records ' + files);
  }
  async function open() {
    await call('Page.navigate', {url: target + '?mini'});
    await wait(`globalThis.Module?.profileReady && document.querySelector('#loading-screen').classList.contains('is-hidden')`);
  }
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Fetch.enable', {patterns: [{urlPattern: 'https://api.waozi.xyz/api/v1/publications/*'}]});
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 700, deviceScaleFactor: 1, mobile: true});

  await open();
  await count(builtIn + 1);
  assert(served >= 1, 'The game never asked the node for its campaign');

  // The approved campaign stays after a reload, even while the node is
  // unreachable, once the browser has saved it (the host saves every second).
  await wait(`Module.FS.readdir('/kryon-apps/shovey').includes('live-campaign-mark')`);
  await delay(2500);
  serving = null;
  await open();
  await count(builtIn + 1);

  // A campaign whose routes do not all win never replaces the levels.
  serving = broken;
  await call('Runtime.evaluate', {awaitPromise: true, expression: `new Promise(resolve => {
    Module.FS.readdir('/kryon-apps/shovey').filter(name => name.startsWith('live-campaign')).forEach(name => Module.FS.unlink('/kryon-apps/shovey/' + name));
    Module.FS.syncfs(false, resolve);
  })`});
  await open();
  await delay(3000);
  await count(builtIn);
  assert.equal(failures.length, 0, failures.join('|'));
  console.log(`Live campaign: the game loads ${builtIn + 1} node levels, keeps them offline after a reload and refuses a campaign with a losing route; no screenshots.`);
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
