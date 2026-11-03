// Exercise the built browser host with real signed accounts and a local node.
// CDP replaces transport only; the page and signed client keep their canonical
// origins. Every other network destination is blocked in this private browser.
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {readFile, writeFile, mkdir, mkdtemp, rm, cp} from 'node:fs/promises';
import {createServer} from 'node:http';
import {resolve, join, extname, sep} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {driverSetup} from './web_driver.mjs';

const project = resolve(new URL('..', import.meta.url).pathname);
const projects = resolve(project, '../../..');
const output = join(project, 'work/referral-host/web-ui');
assert.equal(spawnSync('git', ['check-ignore', '-q', output], {cwd: project}).status, 0);
await mkdir(output, {recursive: true});
const privateRoot = await mkdtemp(join(output, 'run-'));
const webRoot = resolve(process.env.WEB_TEST_ROOT || join(project, 'build/web'));
const preloadManifest = JSON.parse(await readFile(join(webRoot, 'preload-manifest.json'), 'utf8'));
assert(preloadManifest.some(file => file.path === '/entity.zx'));
assert(preloadManifest.some(file => file.path.startsWith('/assets/shovey/world-map/')));
let verifiedPreloads = false;
const pageOrigin = 'https://shovey.waozi.xyz';
const nodeOrigin = 'https://api.waozi.xyz';
const environment = {...process.env, YUE_DESKTOP_RECOVERY: '0'};
for (const key of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
  'SESSION_MANAGER', 'GDK_DISPLAY', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy'])
  delete environment[key];
environment.NO_PROXY = '*';
const fixture = spawn(join(projects, 'kryonlabs/daochi/work/referral-fixture.test'),
  ['-test.run', '^TestReferralBrowserFixture$', '-test.v', '-test.timeout=30m'], {
    cwd: join(projects, 'kryonlabs/daochi'),
    env: {...environment, DAOCHI_REFERRAL_FIXTURE_REPORT: join(privateRoot, 'fixture.json')},
    stdio: ['ignore', 'ignore', 'pipe']
  });
let fixtureErrors = '';
fixture.stderr.on('data', bytes => fixtureErrors = (fixtureErrors + bytes).slice(-2000));
const browsers = new Set();
const mime = {'.js': 'text/javascript', '.wasm': 'application/wasm', '.html': 'text/html',
  '.json': 'application/json', '.webp': 'image/webp', '.png': 'image/png',
  '.css': 'text/css', '.svg': 'image/svg+xml'};
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, 'http://localhost');
    const path = resolve(webRoot, '.' + decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname));
    assert(path.startsWith(webRoot + sep));
    const bytes = await readFile(path);
    response.setHeader('Content-Type', mime[extname(path)] || 'application/octet-stream');
    response.end(bytes);
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const staticOrigin = `http://127.0.0.1:${server.address().port}`;

async function until(predicate, label, timeout = 60000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await predicate();
    if (value) return value;
    await delay(80);
  }
  throw Error(label);
}

async function stop(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const exited = new Promise(done => child.once('exit', done));
  const signal = value => {
    try { if (child.spawnargs.includes('--headless')) process.kill(-child.pid, value); else child.kill(value); }
    catch (error) { if (error.code !== 'ESRCH') throw error; }
  };
  signal('SIGTERM');
  const timer = setTimeout(() => signal('SIGKILL'), 5000);
  await exited;
  clearTimeout(timer);
}

try {
  const metadata = await until(async () => {
    assert.equal(fixture.exitCode, null, 'Fixture stopped: ' + fixtureErrors);
    try { return JSON.parse(await readFile(join(privateRoot, 'fixture.json'), 'utf8')); }
    catch { return null; }
  }, 'Fixture did not start');
  assert(metadata.synthetic && metadata.real_mldsa && metadata.authority === nodeOrigin);
  assert(metadata.url.startsWith('http://127.0.0.1:'));

  async function control(path, body = {}) {
    const response = await fetch(metadata.url + '/fixture/' + path, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Fixture-Key': metadata.control_key},
      body: JSON.stringify(body)});
    assert(response.ok, 'Fixture control failed: ' + path + ' ' + response.status);
    return response.json();
  }

  async function application(name, action) {
    const profile = join(privateRoot, name);
    await mkdir(profile, {recursive: true});
    // These belong to the stopped private browser, not the saved account.
    // A copied profile needs fresh locks and its new debugging endpoint.
    for (const file of ['DevToolsActivePort', 'SingletonLock', 'SingletonCookie', 'SingletonSocket'])
      await rm(join(profile, file), {force: true});
    const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox',
      '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
      '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'],
      {detached: true, env: environment, stdio: ['ignore', 'ignore', 'pipe']});
    browsers.add(browser);
    let errors = '';
    let stage = 'starting actual host';
    let delayedAccepted, claimPosts = 0;
    browser.stderr.on('data', bytes => errors = (errors + bytes).slice(-2000));
    let socket;
    let debug;
    try {
      const port = await until(async () => {
        assert.equal(browser.exitCode, null, 'Private Chromium stopped: ' + errors);
        try { return (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; }
        catch { return null; }
      }, 'Private Chromium did not start');
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
      await new Promise(done => socket.addEventListener('open', done, {once: true}));
      let serial = 0;
      const pending = new Map(), transportErrors = [];
      socket.addEventListener('message', event => {
        const message = JSON.parse(event.data);
        if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
        if (message.method === 'Fetch.requestPaused')
          transport(message.params).catch(error => transportErrors.push(String(error)));
      });
      async function call(method, params = {}) {
        const id = ++serial;
        const answer = new Promise((done, reject) => {
          pending.set(id, done);
          setTimeout(() => {
            if (pending.delete(id)) reject(Error('CDP request timed out: ' + method + ' while ' + stage));
          }, 90000).unref();
        });
        socket.send(JSON.stringify({id, method, params}));
        const result = await answer;
        assert(!result.error, method + ': ' + result.error?.message);
        return result.result;
      }
      async function transport({requestId, request}) {
        const url = new URL(request.url);
        let target;
        if (url.origin === pageOrigin) target = staticOrigin + url.pathname + url.search;
        else if (url.origin === nodeOrigin) target = metadata.url + url.pathname + url.search;
        else { await call('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'}); return; }
        try {
          if (url.origin === nodeOrigin && url.pathname === '/api/v1/referrals/claim' && request.method === 'POST') claimPosts++;
          const headers = {...request.headers};
          for (const key of Object.keys(headers))
            if (['host', 'connection', 'content-length', 'accept-encoding'].includes(key.toLowerCase())) delete headers[key];
          const response = await fetch(target, {method: request.method, headers,
            body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.postData});
          const responseHeaders = [...response.headers].filter(([key]) =>
            !['content-length', 'content-encoding', 'transfer-encoding', 'connection'].includes(key));
          const bytes = Buffer.from(await response.arrayBuffer());
          const delayed = delayedAccepted && !delayedAccepted.observed &&
            url.origin === nodeOrigin && url.pathname === '/api/v1/referrals/accepted' && request.method === 'GET'
            ? delayedAccepted : null;
          if (delayed) {
            assert.equal(response.status, 200, 'Delayed response was not an authenticated accepted list');
            assert(bytes.toString().includes(delayed.person), 'Delayed list did not belong to A');
            delayed.observed = true;
            await delayed.gate;
          }
          try {
            await call('Fetch.fulfillRequest', {requestId, responseCode: response.status,
              responseHeaders: responseHeaders.map(([name, value]) => ({name, value})),
              body: bytes.toString('base64')});
          } catch (error) {
            // Logout may already have cancelled A's browser request. Both the
            // cancellation and a delivered late response must leave B clean.
            if (!delayed || !/Invalid InterceptionId|Invalid interception|Invalid requestId/i.test(String(error))) throw error;
            delayed.cancelled = true;
          } finally {
            if (delayed) delayed.completed = true;
          }
        } catch (error) {
          await call('Fetch.failRequest', {requestId, errorReason: 'Failed'});
          throw error;
        }
      }
      async function evaluate(expression, awaitPromise = false) {
        const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise});
        assert(!result.exceptionDetails, 'Browser evaluation failed');
        return result.result.value;
      }
      await call('Runtime.enable');
      await call('Page.enable');
      await call('Page.addScriptToEvaluateOnNewDocument', {source: driverSetup});
      await call('Fetch.enable', {patterns: [{urlPattern: '*'}]});
      await call('Emulation.setDeviceMetricsOverride', {width: 900, height: 1500, deviceScaleFactor: 1, mobile: false});
      console.log(name + ': loading the actual browser host');
      await call('Page.navigate', {url: pageOrigin + '/'});
      await until(() => evaluate('Boolean(globalThis.Module?.profileReady && Module.FS)'), 'Actual Profile provider not ready');
      if (!verifiedPreloads) {
        const failures = await evaluate(`(async () => {
          const failures = [];
          for (const file of ${JSON.stringify(preloadManifest)}) {
            try {
              const bytes = Module.FS.readFile(file.path);
              const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
                .map(value => value.toString(16).padStart(2, '0')).join('');
              if (bytes.length !== file.bytes || hash !== file.sha256) failures.push(file.path);
            } catch { failures.push(file.path); }
          }
          return failures;
        })()`, true);
        assert.deepEqual(failures, [], 'Preloaded resources differ from the original build inputs');
        verifiedPreloads = true;
        console.log('Actual browser verified every preload: ' + preloadManifest.length + ' original resources');
      }
      stage = 'driving ' + name + ' signup and referrals';
      console.log(name + ': actual host ready');
      let driverSerial = 0;
      async function send(verb, fields = {}) {
        const escape = value => String(value).replaceAll('\\', '\\\\').replaceAll('\t', '\\t').replaceAll('\n', '\\n');
        const text = [++driverSerial, verb, ...Object.entries(fields).map(([key, value]) => key + '=' + escape(value))].join('\t') + '\n';
        await evaluate(`(() => { const fs=Module.FS; if(fs.analyzePath('/tmp/test-driver/reply').exists)fs.unlink('/tmp/test-driver/reply'); fs.writeFile('/tmp/test-driver/command',${JSON.stringify(text)}); })()`);
        await until(() => evaluate("Module.FS.analyzePath('/tmp/test-driver/reply').exists"), 'No committed UI driver reply');
        const reply = JSON.parse(await evaluate("Module.FS.readFile('/tmp/test-driver/reply',{encoding:'utf8'})"));
        assert(reply.ok, 'UI command failed: ' + verb);
        return reply;
      }
      const tree = async () => (await send('tree')).nodes;
      debug = async () => ({stage, nodes: await tree(), transportErrors});
      const key = async value => (await tree()).find(node => node.key === value);
      async function press(selector) {
        for (let attempt = 0; attempt < 20; attempt++) {
          const nodes = await tree();
          const found = nodes.find(node => node.visible && Object.entries(selector).every(([name, value]) =>
            name === 'role' ? node.role === value || node.kind === value : node[name] === value));
          // Preserve the selector: arbitrary u64 keys lose precision in JS.
          if (found) { await send('press', {...selector, visible: 1}); return; }
          await send('pointer', {x: 450, y: 600, wheel: -6});
        }
        throw Error('Missing visible UI control: ' + JSON.stringify(selector));
      }
      async function referrals() {
        if (!await evaluate('Boolean(Module.profileVisible)')) {
          await press({key: 20400});
          await until(() => evaluate('Boolean(Module.profileVisible)'), 'Profile did not open');
        }
        if (!await key(78003)) await press({key: 78030});
        await until(() => key(78003), 'Referrals did not open');
      }
      async function create() {
        await referrals();
        await press({key: 78005});
        await press({key: 820});
        const account = await until(async () => evaluate(`(() => { const p='/kryon-apps/profile/account.key'; if(!Module.FS.analyzePath(p).exists)return ''; const text=Module.FS.readFile(p,{encoding:'utf8'}); return text.match(/^public_id=([0-9a-f]{64})$/m)?.[1]||''; })()`), 'Current provider did not save its public account ID');
        await until(async () => {
          if (await key(78003)) return true;
          const nodes = await tree();
          if (nodes.some(node => node.key === 78030 && node.visible)) await press({key: 78030});
          else if (nodes.some(node => node.label === 'Not now' && node.visible)) await press({label: 'Not now'});
          else if (nodes.some(node => node.label === 'Back' && node.visible)) await press({label: 'Back'});
          else if (nodes.some(node => node.key === 49001 && node.visible)) await press({key: 49001});
          return false;
        }, 'Signup did not return to referral review');
        await until(() => key(78010), 'Signed referral summary did not confirm current account');
        return account;
      }
      async function logout() {
        if (await key(78003)) await press({key:await key(78002) ? 78002 : 49001});
        await press({key:830});
        await until(async () => (await key(8808)) || (await key(820)), 'Sign-out did not reach its confirmation');
        if (await key(8808)) await press({key:8808});
        await until(()=>key(820),'Actual account provider did not sign out');
        assert(!await key(78006), 'A receipt survived logout');
        assert(!(await tree()).some(node=>node.key>=78100 && node.key<78400),'A list survived logout');
      }
      function delayAccepted(person) {
        assert(!delayedAccepted,'A delayed response was already armed');
        let resume;
        delayedAccepted={person,observed:false,completed:false,gate:new Promise(done=>resume=done),resume};
        return {
          seen:()=>until(()=>delayedAccepted.observed,'A did not start an authenticated list refresh'),
          release:async()=>{delayedAccepted.resume(); await until(()=>delayedAccepted.completed,'Delayed A response did not complete');}
        };
      }
      await action({create, referrals, press, key, tree, send, logout, delayAccepted,
        claims:()=>claimPosts});
      assert(await evaluate(`(async () => {
        if (Module.__inbeFlushStorageSync) return await Module.__inbeFlushStorageSync(true);
        return await new Promise(done => Module.FS.syncfs(false,error => done(!error)));
      })()`, true), 'The actual browser store did not persist its account');
      assert.deepEqual(transportErrors, [], 'Local test transport failed');
    } catch (error) {
      if (debug) {
        try { await writeFile(join(output, name + '-failure.json'), JSON.stringify(await debug(), null, 2)); }
        catch {}
      }
      throw error;
    } finally {
      delayedAccepted?.resume();
      socket?.close();
      await stop(browser);
      browsers.delete(browser);
    }
  }

  let inviter, friend, invitation;
  await application('inviter', async driver => {
    inviter = await driver.create();
    invitation = (await control('seed', {account_id: inviter, count: 1})).code;
  });
  await application('friend', async driver => {
    friend = await driver.create();
    assert.notEqual(friend, inviter);
    await driver.press({key: 107});
    await driver.send('type', {text: invitation});
    await driver.press({key: 78024});
    assert(!await driver.key(78006), 'Review accepted without confirmation');
    await driver.press({key: 78022});
    const gift = await until(() => driver.key(78006), 'No immediate no-purchase welcome confirmation');
    assert(/\b20\b/.test(gift.label || ''), 'The immediate welcome confirmation did not show 20 Dew');
    assert(!await driver.key(78024), 'Successful claim still offered');
  });
  await cp(join(privateRoot, 'friend'), join(privateRoot, 'friend-device'), {recursive: true});
  await application('friend-device', async driver => {
    await driver.referrals();
    await until(() => driver.key(78018), 'Global referrer missing from another private browser');
    assert(!await driver.key(78024), 'Another private browser offered a duplicate claim');
  });
  await application('inviter', async driver => {
    await driver.referrals();
    const person = await until(async () => (await driver.tree()).find(node => node.label?.includes(friend)),
      'Accepted nonpurchaser absent from inviter list');
    const date = await driver.key(person.key + 1);
    assert(/\d{4}-\d{2}-\d{2}/.test(date?.label || ''), 'Acceptance date missing');
  });
  let upstreamCode;
  await application('upstream', async driver => {
    await driver.create();
    upstreamCode=(await driver.key(78010)).label;
    assert(upstreamCode && upstreamCode!==invitation);
  });
  await application('inviter', async driver => {
    await driver.referrals();
    await until(async () => (await driver.tree()).some(node=>node.label?.includes(friend)),
      'A lost its accepted friend before the boundary test');
    await driver.press({key:107});
    await driver.send('type',{text:upstreamCode});
    await driver.press({key:78024});
    assert(await driver.key(78022),'A never entered explicit confirmation');
    await driver.press({key:78022});
    await until(()=>driver.key(78006),'A never received its signed welcome receipt');
    const claimsBeforeSwitch=driver.claims();
    const delayed=driver.delayAccepted(friend);
    await driver.press({key:78009});
    await delayed.seen();
    await driver.logout();
    const accountB=await driver.create();
    assert.notEqual(accountB,inviter,'UI signup did not switch A to a new account B');
    const codeB=(await driver.key(78010)).label;
    assert.notEqual(codeB,invitation,'B displayed A’s invite code');
    const assertB=async()=>{
      const nodes=await driver.tree();
      assert(!nodes.some(node=>[78006,78018,78020,78021,78022].includes(node.key)),
        'A receipt, referrer or prior confirmation appeared under B');
      assert(!nodes.some(node=>node.label?.includes(friend)),'A’s accepted list appeared under B');
      assert(!nodes.some(node=>node.key===107 && node.value?.includes(upstreamCode)),
        'A’s accepted code was replayed into B’s input');
      assert.equal(driver.claims(),claimsBeforeSwitch,'Prior code acceptance was replayed after logout/account switch');
    };
    await assertB();
    await delayed.release();
    for(let frame=0;frame<20;frame++){await assertB(); await delay(100);}
    await until(()=>driver.key(78026),'B did not show its own empty accepted list');
  });
  await control('stop');
  await writeFile(join(output, 'result.json'), JSON.stringify({app: 'shovey', canonical_origins: true,
    real_signed_provider: true, no_purchase_welcome: true, accepted_nonpurchaser_date: true,
    explicit_confirmation: true, second_browser_binding: true, logout: true,
    delayed_owner_switch: true, no_confirmation_or_claim_replay: true,
    preloaded_resources_verified: preloadManifest.length}) + '\n');
  console.log('Shovey actual browser: signed signup, explicit no-purchase gift, accepted friend/date persistent global binding, logout and delayed-response A→B isolation passed');
} finally {
  for (const browser of browsers) await stop(browser);
  await stop(fixture);
  await new Promise(done => server.close(done));
  await rm(privateRoot, {recursive: true, force: true});
}
