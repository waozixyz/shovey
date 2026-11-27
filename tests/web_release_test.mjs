// shovey.waozi.xyz as published: the released Shovey in Arcade's browser
// host, built by scripts/build-site.py. Plays level 1 in the packaged public
// host or on the deployed site. The private test build also checks its UI tree.
// No pixel captures.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {driverSetup} from './web_driver.mjs';

const liveUrl = process.env.SHOVEY_TEST_URL;
const sitePath = process.argv[2];
const root = sitePath || new URL('../build/web-site/', import.meta.url).pathname;
const publicHost = Boolean(liveUrl) || !sitePath || process.env.SHOVEY_PUBLIC_HOST === '1';
const profile = await mkdtemp(join(tmpdir(), 'shovey-release-'));
const gameplayControls = [20022, 20820, 20016, 20017, 20023];
const isGameplay = nodes => gameplayControls.every(key => nodes.some(node => node.key === key)) &&
  nodes.some(node => node.label === 'Wall' && (node.role === 'image' || node.kind === 'image'));
const types = {'.html': 'text/html', '.wasm': 'application/wasm', '.js': 'text/javascript', '.png': 'image/png', '.jpg': 'image/jpeg', '.json': 'application/json'};
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
    response.setHeader('Content-Type', path === '/' ? 'text/html' : types[path.slice(path.lastIndexOf('.'))] || 'application/octet-stream');
    response.end(body);
  } catch {
    // Like Cloudflare Pages, a missing file gets the site's page.
    try { response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'}).end(await readFile(join(root, 'index.html'))); }
    catch { response.writeHead(404).end(); }
  }
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
  async function wait(expression, retry = () => delay(100)) {
    for (let end = Date.now() + 60000; Date.now() < end;) {
      assert.deepEqual(failures, []);
      if (await evaluate(expression)) return;
      await retry();
    }
    throw Error('Timed out: ' + expression + '; page: ' + await evaluate(`JSON.stringify({type:document.contentType,url:location.href,module:!!globalThis.Module,loading:document.querySelector('#loading')?.className})`) + '; console: ' + lines.slice(-10).join(' | '));
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
  async function playWithDriver() {
    await wait(`Module.FS.analyzePath('/tmp/test-driver').exists`);
    await delay(1500);
    await press('Not now');
    assert(await press('Play'), 'No Play button: ' + (await tree()).map(node => node.label).join('|'));
    // Play opens the map, which focuses Level 1 on a fresh profile; its Play starts it.
    for (let end = Date.now() + 30000; Date.now() < end;) {
      const nodes = await tree(), labels = nodes.map(node => node.label);
      const mapPlay = nodes.find(node => node.key === 20122);
      if (labels.includes('How do you want to move?')) await press('Swipe and tap');
      else if (isGameplay(nodes)) break;
      else if (mapPlay && nodes.some(node => node.key === 20121 && node.label === 'Level 1'))
        await click(mapPlay.x + mapPlay.width / 2, mapPlay.y + mapPlay.height / 2);
      await delay(250);
    }
    assert(isGameplay(await tree()), 'Level 1 did not open with the shared gameplay controls');
    assert(!(await tree()).some(node => /^Level 1 \//.test(node.label)), 'Removed gameplay heading returned');
    const frames = evaluate(`new Promise(done => { let count = 0, start = performance.now(); function frame(now) { count++; if (now - start < 3000) requestAnimationFrame(frame); else done(count); } requestAnimationFrame(frame); })`);
    for (let step = 0; step < 10; step++) { await key(step % 2 ? 'ArrowLeft' : 'ArrowRight', step % 2 ? 37 : 39); await delay(200); }
    assert(await frames > 30, 'The level stopped drawing while walking');
    return 'level 1, private gameplay controls';
  }
  async function playPublicHost() {
    // The fresh guest profile uses the fixed 720×1280 viewport below. Read
    // records written by the actual controls to verify each click and move.
    const records = '/kryon-apps/arcade/games/arcade.shovey';
    const read = path => {
      const file = JSON.stringify(path);
      return `(Module.FS.analyzePath(${file}).exists ? Module.FS.readFile(${file}, {encoding: 'utf8'}) : null)`;
    };
    const updates = read(`${records}-player/records/level-updates`);
    const controls = read(`${records}/records/controls`);
    const progress = `JSON.parse(${read(`${records}/records/local.path.meta`)})`;

    await wait(`document.getElementById('loading').classList.contains('done')`);
    // A cover takes input after its art has loaded. Retry each action until
    // its corresponding record confirms the transition.
    await wait(`${updates} === 'off'`, () => click(249, 698)); // Not now
    await wait(`${progress}?.level === 1`, () => click(360, 1116)); // Play Classic
    await wait(`${controls} === 'off'`, () => click(208, 665)); // Swipe and tap

    const before = await evaluate(progress);
    assert.equal(before.moves, 0, 'Level 1 did not open at its starting position');
    await key('ArrowLeft', 37);
    await wait(`${progress}?.moves === 1`);
    const after = await evaluate(progress);
    assert.equal(after.level, 1);
    // The checkpoint stores its player cell in the two hex digits after its level.
    for (const state of [before, after]) assert.match(state.checkpoint, /^P[123]01[0-9a-f]{2}/);
    const cells = [before, after].map(state => Number.parseInt(state.checkpoint.slice(4, 6), 16));
    assert.equal(cells[1], cells[0] - 1, 'Shovey did not walk left in level 1');
    return `level 1, player cell ${cells[0]} → ${cells[1]}`;
  }
  await call('Runtime.enable');
  await call('Page.enable');
  if (!publicHost) await call('Page.addScriptToEvaluateOnNewDocument', {source: driverSetup});
  await call('Emulation.setDeviceMetricsOverride', {width: 720, height: 1280, deviceScaleFactor: 1, mobile: true});
  const target = new URL(liveUrl || `http://127.0.0.1:${server.address().port}/`);
  const landing = publicHost && !target.search;
  if (!landing && !target.search) target.search = '?play';
  const navigation = await call('Page.navigate', {url: target.href});
  assert(!navigation.errorText, navigation.errorText);
  if (landing) await wait(`document.readyState === 'complete' && location.href === ${JSON.stringify(target.href)}`);
  const previousSite = landing && liveUrl && await evaluate('!!globalThis.Module && !document.querySelector("#landing")');
  if (landing && !previousSite) {
    const playLink = `Array.from(document.querySelectorAll('#landing a[href="?play"]')).find(link => link.getClientRects().length)`;
    assert(await evaluate(`!!${playLink}`), 'The landing page is missing its Play link');
    assert(await evaluate(`!!document.getElementById('landing-style')?.sheet.cssRules.length`), 'The landing stylesheet did not load');
    assert(await evaluate(`!globalThis.Module && !performance.getEntriesByType('resource').some(entry => {
      const path = new URL(entry.name).pathname;
      return path.startsWith('/runtime.') || path === '/arcade.json';
    })`), 'The landing page started downloading the game');
    await evaluate(`${playLink}.focus()`);
    await key('Enter', 13);
    await wait(`location.search === '?play'`);
  }
  await wait(`!!(globalThis.Module && Module.profileReady) || !!document.getElementById('loading')?.classList.contains('error')`);
  assert.equal(await evaluate('location.origin'), target.origin, 'Shovey opened on a different origin');
  assert(!await evaluate(`document.getElementById('loading').classList.contains('error')`), 'The page could not start Shovey');
  const runtime = (await evaluate(`performance.getEntriesByType('resource').map(entry => entry.name)`)).map(name => new URL(name))
    .filter(url => /\/(runtime\.(js|wasm|data)(\.gz)?|arcade\.json|apps\.zx(\.gz)?)$/.test(url.pathname));
  const revisions = new Set(runtime.map(url => url.searchParams.get('v')));
  assert(runtime.some(url => url.pathname === '/runtime.js') && runtime.some(url => url.pathname === '/runtime.wasm') &&
    revisions.size === 1 && /^[0-9a-f]{64}$/.test([...revisions][0]),
  'The runtime files did not share one cache revision: ' + runtime.map(url => url.pathname + url.search).join(' '));
  if (publicHost) {
    const build = await evaluate(`fetch('/build.json', {cache: 'no-store'}).then(response => response.json())`);
    assert.equal([...revisions][0], build.assets_sha256, 'The page did not load the runtime from build.json');
  }
  // Only a real bundle may stand in for the release's own Apps controller.
  assert(await evaluate(`!Module.FS.analyzePath('/apps.zx').exists || String.fromCharCode(...Module.FS.readFile('/apps.zx').slice(0, 2)) === 'ZX'`),
    'The page took a file the site does not have for the Apps controller');
  const gameplay = publicHost ? await playPublicHost() : await playWithDriver();
  const failed = lines.find(line => /frame failed|portable execution failed|cannot run natively/.test(line));
  assert(!failed, failed);
  // The current runtime compiles the exact released bundles at instantiation.
  const modules = await evaluate('globalThis.zxWasmTier?.modules.size');
  assert(modules >= 4,
    'The player did not compile the collection, Apps controller, Profile and game to WebAssembly');
  assert.deepEqual(failures, []);
  console.log(`${target} played ${gameplay} with ${modules} compiled WebAssembly modules`);
} finally {
  try { socket?.close(); } catch {}
  try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
  server.close();
  await rm(profile, {recursive: true, force: true}).catch(() => {});
}
