// Verify the actual browser host through input, rendered text and private storage; no pixel captures.
// Exercise Shovey's level selector in its real web shell, with a private profile.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const root = new URL('../build/web/', import.meta.url).pathname;
const profile = await mkdtemp(join(tmpdir(), 'shovey-profile-'));
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
    for (let end = Date.now() + 45000; Date.now() < end;) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    const state = await evaluate(`JSON.stringify({ready:globalThis.Module?.profileReady,status:document.querySelector('#status')?.textContent,result:document.querySelector('#result')?.textContent})`);
    throw Error('Timed out: ' + expression + '; state: ' + state + '; errors: ' + failures.join('|'));
  }
  async function click(x, y) {
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1});
    await delay(100);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1});
    await delay(400);
  }
  await call('Runtime.enable');
  await call('Page.enable');
  console.log('Browser connected');
  await call('Page.addScriptToEvaluateOnNewDocument', {source: `
    document.addEventListener('DOMContentLoaded', () => {
      globalThis.profileTestHook = true;
      Module.preRun = Module.preRun || [];
      Module.preRun.push(function() {
        ENV.KRYON_TEST_DRIVER = '/tmp/test-driver';
        Module.FS.mkdirTree('/tmp/test-driver');
      });
    }, {once:true});
  `});
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await call('Page.reload');
  await wait(`globalThis.Module?.profileReady && document.querySelector('#loading-screen').classList.contains('is-hidden')`);
  assert(await evaluate(`Module.FS.analyzePath('/tmp/test-driver').exists`), 'Driver init: ' + await evaluate('JSON.stringify({hook:globalThis.profileTestHook, pre:Module.preRun?.length})'));
  let serial = 0;
  async function tree() {
    const command = (++serial) + '\ttree\n';
    await evaluate(`Module.FS.writeFile('/tmp/test-driver/command', ${JSON.stringify(command)})`);
    await wait(`Module.FS.analyzePath('/tmp/test-driver/reply').exists`);
    const reply = await evaluate(`Module.FS.readFile('/tmp/test-driver/reply', {encoding: 'utf8'})`);
    await evaluate(`Module.FS.unlink('/tmp/test-driver/reply')`);
    const result = JSON.parse(reply);
    assert(result.ok, JSON.stringify(result));
    return result.nodes;
  }
  async function labels() { return (await tree()).map(node => node.label); }
  async function textClick(label) {
    const nodes = await tree();
    const row = nodes.find(node => node.label === label && (node.role === 'button' || node.kind === 'button'));
    assert(row, 'Missing control: ' + label + '; buttons: ' + nodes.filter(n => (n.role === 'button' || n.kind === 'button')).map(n => n.label).join('|'));
    await click(row.x + row.width / 2, row.y + row.height / 2);
  }
  console.log('Opening Profile');
  await click(352, 31);
  await wait('Module.profileVisible');
  await delay(600);
  let profileText = await labels();
  assert(profileText.includes('Dew balance'), profileText.join('|'));
  assert(!profileText.includes('Name') && !profileText.includes('Intention'));
  await textClick('Connect an account');
  if (process.env.WEB_FAIL_STORAGE) {
    await evaluate(`Module.FS.syncfs = function(populate, callback) { setTimeout(() => callback(new Error('Storage fixture refused the write')), 0); }`);
  }
  await textClick('Create account');
  let connected = false, refused = false;
  for (const end = Date.now() + 20000; Date.now() < end;) {
    const text = await labels();
    if (text.includes('Account connected on this device')) { connected = true; break; }
    if (text.some(label => /could not|couldn't|failed/i.test(label))) { refused = true; break; }
    await delay(20);
  }
  if (process.env.WEB_FAIL_STORAGE) {
    assert(refused && !connected, 'A refused storage write was reported as connected');
    assert(!await evaluate(`Module.FS.analyzePath('/kryon-apps/profile/account.key').exists`), 'Failed account creation left a replacement key');
    console.log('Refused browser account storage stays disconnected and removes the unsaved key; no screenshots.');
  } else {
    assert(connected, 'Account creation did not finish');
    await call('Page.reload');
    await wait('globalThis.Module?.profileReady');
    assert(await evaluate(`Module.FS.analyzePath('/kryon-apps/profile/account.key').exists`), 'Confirmed account was lost on immediate reload');
    await click(352, 31);
    await wait('Module.profileVisible');
    profileText = await labels();
    assert(profileText.includes('Dew balance'));
    assert(!profileText.includes('Connect an account'), 'Persisted account was not restored');
    if (process.env.WEB_VERIFY_NODE) {
      let confirmed = false;
      for (const end = Date.now() + 25000; Date.now() < end;) {
        const text = await labels();
        if (text.some(label => /^\d+(?:\.\d+)? Dew$/.test(label))) { confirmed = true; break; }
        await delay(150);
      }
      assert(confirmed, 'The node did not confirm the inline Dew balance');
    }
    await click(40, 28);
    await wait('!Module.profileVisible');
    await click(195, 680);
    await wait(`Module.FS.analyzePath('/kryon-apps/shovey/campaign').exists`);
    const campaign = await evaluate(`Module.FS.readFile('/kryon-apps/shovey/campaign', {encoding: 'utf8'})`);
    assert(campaign.length > 0);
    await click(114, 26);
    assert((await labels()).some(text => text.includes('Level')));
    await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x: 195, y: 500, deltaX: 0, deltaY: 2200});
    await delay(500);
    assert.equal(await evaluate(`Module.FS.readFile('/kryon-apps/shovey/campaign', {encoding: 'utf8'})`), campaign, 'Scrolling changed progress');
    console.log('Web Profile, inline Dew, game identity, account creation/persistence and level navigation passed; no screenshots.');
  }
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
