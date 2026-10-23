// Embed the actual web build with ?mini in a taller page, as waozi.xyz does,
// and check that it opens straight into a level without Profile or the title
// screen, and that the wheel over it never scrolls the embedding page.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = process.env.WEB_TEST_ROOT || new URL('../build/web/', import.meta.url).pathname;
const profile = await mkdtemp(join(tmpdir(), 'shovey-mini-'));
const embed = `<!doctype html><meta charset="utf-8"><style>body{margin:0}iframe{display:block;margin:200px 20px;border:0}</style>
<div style="height:200px"></div><iframe id="mini" src="/index.html?mini&theme=waozi" width="390" height="600"></iframe><div style="height:3000px"></div>`;
const driver = `document.addEventListener('DOMContentLoaded', () => {
  Module.preRun = Module.preRun || [];
  Module.preRun.push(function() { ENV.KRYON_TEST_DRIVER = '/tmp/test-driver'; Module.FS.mkdirTree('/tmp/test-driver'); });
}, {once:true});`;
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (path.includes('..')) throw Error('Invalid path');
    if (path === '/embed.html') { response.setHeader('Content-Type', 'text/html'); response.end(embed); return; }
    // DevTools does not script a new child frame, so the served game page
    // turns on its widget test driver itself.
    if (path === '/index.html') {
      const page = (await readFile(join(root, 'index.html'), 'utf8')).replace('<head>', `<head><script>${driver}</script>`);
      response.setHeader('Content-Type', 'text/html'); response.end(page); return;
    }
    response.setHeader('Content-Type', path.endsWith('.wasm') ? 'application/wasm' : path.endsWith('.js') ? 'text/javascript' : path.endsWith('.png') ? 'image/png' : 'text/html');
    response.end(await readFile(join(root, path === '/' ? 'index.html' : path)));
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const target = `http://127.0.0.1:${server.address().port}/embed.html`;
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
  async function wait(expression) {
    for (let end = Date.now() + 60000; Date.now() < end;) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw Error('Timed out: ' + expression + '; errors: ' + failures.join('|'));
  }
  const mini = 'document.getElementById("mini").contentWindow';
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride', {width: 800, height: 900, deviceScaleFactor: 1, mobile: false});
  await call('Page.navigate', {url: target});
  // While the game is still loading, the wheel over it already stays inside.
  await wait(`document.getElementById('mini').contentDocument?.getElementById('loading-screen')`);
  {
    const early = JSON.parse(await evaluate(`JSON.stringify(document.getElementById('mini').getBoundingClientRect())`));
    await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x: early.x + early.width / 2, y: early.y + early.height / 2, deltaX: 0, deltaY: 600});
    await delay(400);
    assert.equal(await evaluate('window.scrollY'), 0, 'The wheel over the loading game scrolled the page');
  }
  // The ZIB edition waits for its profile; the compiled one has none.
  await wait(`(${mini}?.Module?.profileReady || ${mini}?.Module?.FS?.analyzePath('/assets/shovey/catalog.json').exists) && ${mini}.document.querySelector('#loading-screen').classList.contains('is-hidden')`);
  // The embedded page's test driver lists the widgets it drew; nothing is captured.
  let serial = 0;
  async function nodes() {
    const command = (++serial) + '\ttree\n';
    await evaluate(`${mini}.Module.FS.writeFile('/tmp/test-driver/command', ${JSON.stringify(command)})`);
    await wait(`${mini}.Module.FS.analyzePath('/tmp/test-driver/reply').exists`);
    const reply = await evaluate(`${mini}.Module.FS.readFile('/tmp/test-driver/reply', {encoding: 'utf8'})`);
    await evaluate(`${mini}.Module.FS.unlink('/tmp/test-driver/reply')`);
    const result = JSON.parse(reply);
    assert(result.ok, JSON.stringify(result));
    return result.nodes;
  }
  await delay(800);
  const drawn = await nodes();
  const labels = drawn.map(node => node.label);
  const buttons = drawn.filter(node => node.role === 'button' || node.kind === 'button').map(node => node.label);
  assert(labels.some(label => /^Level \d+ \/ \d+$/.test(label)), 'Mini did not open a level: ' + labels.join('|'));
  assert(buttons.includes('Levels') && buttons.includes('Restart'), 'Mini lost its level controls: ' + buttons.join('|'));
  for (const hidden of ['Profile', 'Back', 'Help', 'Play', 'Mute', 'Unmute'])
    assert(!buttons.includes(hidden), 'Mini shows ' + hidden + ': ' + buttons.join('|'));
  assert.notEqual(await evaluate(`${mini}.Module.profileVisible`), true);

  // The page itself scrolls when the wheel is outside the game.
  await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x: 600, y: 300, deltaX: 0, deltaY: 400});
  await wait('window.scrollY > 0');
  await evaluate('window.scrollTo(0, 0)');
  await wait('window.scrollY === 0');
  const frame = await evaluate(`JSON.stringify(document.getElementById('mini').getBoundingClientRect())`);
  const box = JSON.parse(frame);
  for (let turn = 0; turn < 4; turn++) {
    await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x: box.x + box.width / 2, y: box.y + box.height / 2, deltaX: 0, deltaY: 600});
    await delay(150);
  }
  await delay(500);
  assert.equal(await evaluate('window.scrollY'), 0, 'The wheel over the embedded game scrolled the page');
  assert.equal(failures.length, 0, failures.join('|'));
  console.log('Mini opens straight into a level with only Levels and Restart, and its wheel stays inside the embed; no screenshots.');
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
