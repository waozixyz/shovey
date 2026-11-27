"""Private actual-release browser regression; no Node or owner desktop.
Run through build-queue after prepare-pages.py; requires existing guide-test fixture.
"""
import base64
import functools
import http.server
import json
import os
import re
from pathlib import Path
import socket
import struct
import subprocess
import threading
import time
import tempfile
import urllib.parse
import urllib.request

import sys
import shutil
ROOT = Path(__file__).resolve().parents[1]
WEB = Path(sys.argv[1]).resolve()
WORK = ROOT / 'work/pages-packaging'
WORK.mkdir(parents=True, exist_ok=True)
PROFILE = Path(tempfile.mkdtemp(prefix='p',dir=ROOT/'work'))
PROFILE.mkdir(exist_ok=True)
(PROFILE / 'DevToolsActivePort').unlink(missing_ok=True)
environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ}
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY'):
    environment.pop(key, None)
environment['YUE_DESKTOP_RECOVERY'] = '0'
environment['HARMONY_DESKTOP_RECOVERY'] = '0'
for key in ('LISTEN_PID','LISTEN_FDS','LISTEN_FDNAMES','NOTIFY_SOCKET','XDG_SESSION_ID','XDG_SEAT','XDG_VTNR'):
    environment.pop(key,None)
for key,name in {'HOME':'home','XDG_CONFIG_HOME':'config','XDG_CACHE_HOME':'cache','XDG_DATA_HOME':'data','XDG_STATE_HOME':'state','XDG_RUNTIME_DIR':'runtime','TMPDIR':'tmp'}.items():
    path=PROFILE/name;path.mkdir(mode=0o700,exist_ok=True);environment[key]=str(path)


def world_map_art():
    """The v5 portrait map: level 1's authored centre and each painting's authored bounds."""
    scenes = json.loads((ROOT / 'assets/shovey/world-map/scenes.json').read_text())
    return dict(first=scenes['nodes']['portrait'][0],
                panels=[scene['portrait']['world_bounds_before_zoom'] for scene in scenes['scenes']])


class Handler(http.server.SimpleHTTPRequestHandler):
    mode = 'normal'

    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        if path.path == '/__test':
            Handler.mode = urllib.parse.parse_qs(path.query)['mode'][0]
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK'); return
        if Handler.mode != 'normal' and path.path == '/runtime.data.part-0000':
            if Handler.mode == 'missing':
                self.send_error(404); return
            content = b'<html>SPA fallback</html>' if Handler.mode == 'html' else b'broken'
            if Handler.mode == 'corrupt':
                content = b'X' * (16 * 1024 * 1024)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html' if Handler.mode == 'html' else 'application/octet-stream')
            self.end_headers(); self.wfile.write(content); return
        if Handler.mode == 'path' and path.path == '/runtime.data.json':
            manifest = json.loads((WEB/'runtime.data.json').read_text())
            manifest['chunks'][0]['name'] = '../private'
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.end_headers(); self.wfile.write(json.dumps(manifest).encode()); return
        super().do_GET()

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()
    def log_message(self, format, *args):
        if args[1] != '200':
            print('HTTP', format % args, flush=True)


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(WEB)))
threading.Thread(target=server.serve_forever, daemon=True).start()
log = (WORK / 'browser.log').open('w')
browser = subprocess.Popen(['chromium', '--headless', '--remote-allow-origins=*', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
                            '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
                            '--user-data-dir=' + str(PROFILE), 'about:blank'],
                           env=environment, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
connection = None
events = []
serial = 0
try:
    port_file = PROFILE / 'DevToolsActivePort'
    for _ in range(300):
        if port_file.exists():
            break
        assert browser.poll() is None, 'Chromium exited'
        time.sleep(.1)
    port = int(port_file.read_text().splitlines()[0])
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:
        pages = json.load(response)
    url = urllib.parse.urlparse(next(page for page in pages if page['type'] == 'page')['webSocketDebuggerUrl'])
    connection = socket.create_connection((url.hostname, url.port), timeout=180)
    key = base64.b64encode(os.urandom(16)).decode()
    connection.sendall(f'GET {url.path} HTTP/1.1\r\nHost: {url.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'.encode())
    handshake = bytearray()
    while not handshake.endswith(b'\r\n\r\n'):
        handshake.extend(connection.recv(1))
    assert handshake.startswith(b'HTTP/1.1 101 '), handshake

    def read(count):
        result = bytearray()
        while len(result) < count:
            part = connection.recv(count - len(result))
            assert part, 'Closed DevTools socket'
            result.extend(part)
        return bytes(result)

    def call(method, params=None):
        global serial
        serial += 1
        payload = json.dumps(dict(id=serial, method=method, params=params or {})).encode()
        mask = os.urandom(4)
        if len(payload) < 126:
            header = bytes((0x81, 0x80 | len(payload)))
        elif len(payload) < 65536:
            header = bytes((0x81, 0xfe)) + struct.pack('!H', len(payload))
        else:
            header = bytes((0x81, 0xff)) + struct.pack('!Q', len(payload))
        connection.sendall(header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))
        while True:
            first, second = read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', read(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', read(8))[0]
            incoming_mask = read(4) if second & 128 else None
            body = read(size)
            if incoming_mask:
                body = bytes(byte ^ incoming_mask[index % 4] for index, byte in enumerate(body))
            assert first & 15 == 1, ('Unexpected frame', first)
            message = json.loads(body)
            if message.get('id') == serial:
                assert 'error' not in message, message
                return message['result']
            events.append(message)
            del events[:-100]

    def evaluate(expression):
        result = call('Runtime.evaluate', dict(expression=expression, returnByValue=True))
        assert 'exceptionDetails' not in result, result
        return result.get('result', {}).get('value')

    def wait(expression, seconds=45):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if evaluate(expression):
                return
            time.sleep(.1)
        raise RuntimeError('Timed out: ' + expression)

    call('Runtime.enable')
    target_id = call('Target.createTarget', dict(url='about:blank'))['targetId']
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:
        game = next(p for p in json.load(response) if p['id'] == target_id)
    test = (ROOT / 'tests/web_selector_latest_test.mjs').read_text()
    body = test[test.index('  const pending ='):test.index('} finally {')]
    body = body.replace(').unref();', ');')
    a = body.index("  await press('Play');")
    b = body.index("  await call('Runtime.evaluate', {awaitPromise: true", a)
    guest_ui = """
  globalThis.shoveyTestEvaluate = evaluate;
  globalThis.shoveyBrowserConsole = [];
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.consoleAPICalled')
      { globalThis.shoveyBrowserConsole.push(message.params.args.map(a => a.value ?? a.description).join(' ')); globalThis.shoveyBrowserConsole.splice(0, Math.max(0, globalThis.shoveyBrowserConsole.length - 40)); }
  });
  await wait(async () => (await tree()).some(n => n.key === 49305 && n.visible), 'Initial update choice did not open');
  await pressKey(49305);
  await wait(async () => !(await tree()).some(n => n.key === 49300 && n.visible), 'Initial update choice did not close');
  assert(!(await tree()).some(n => n.key === 49206 && n.visible), 'Guest title trophy is visible');
  await pressKey(49204);
  await wait(async () => (await tree()).some(n => n.label === 'Sign in'), 'Guest Profile did not open');
  const profileNodes = await tree();
  assert(profileNodes.some(n => n.kind === 'image' && n.detail?.includes('title/shovey-')), 'Profile discarded the title background');
  assert(!profileNodes.some(n => n.key === 550 && n.visible), 'Guest Profile leaderboard is visible');
  await key('ArrowRight', 39);
  await key('Escape', 27);
  await wait(async () => actionable(await tree(), 'Play'), 'Modal input changed the cover behind Profile');
  await pressKey(49200);
  await wait(async () => (await tree()).some(n => n.key === 61101), 'Shop did not open');
  assert(!(await tree()).some(n => n.key === 61106 && n.visible), 'Guest shop trophy is visible');
  await pressKey(61104);
  await wait(async () => (await tree()).some(n => n.label === 'Sign in'), 'Shop Profile did not open');
  assert((await tree()).some(n => n.key === 61101 && n.visible), 'Profile discarded the shop background');
  await key('Escape', 27);
  await pressKey(61101);
  await wait(async () => actionable(await tree(), 'Play'), 'Shop did not return to the title');
"""
    body = body[:a] + guest_ui + body[b:]  # Packaging regression starts from earned progress.
    body = body.replace('return reply.nodes;', 'globalThis.shoveyLastTree = reply.nodes; return reply.nodes;')
    # The release host has a separate Levels action and resumes saved games with Continue.
    body = body.replace("n.label === 'Play' &&", "(n.label === 'Play' || n.label === 'Continue') &&")
    body = body.replace("  await press('Play');", """  await pressKey(49224);
  await wait(async () => {
    const nodes = await tree();
    if (nodes.some(n => n.key === 20510 && n.visible)) await pressKey(20510);
    return nodes.some(n => n.key === 20105 && n.visible);
  }, 'Levels did not open the selector');""")
    body = body.replace("document.querySelector('#loading-screen').classList.contains('is-hidden')", "Module.profileReady && document.querySelector('#loading').classList.contains('done')")
    body = body.replace("  await call('Runtime.enable');", "  await call('Page.bringToFront'); await call('Network.enable'); await call('Network.setBlockedURLs', {urls:['https://*']}); await call('Runtime.enable');")
    body = body.replace('/kryon-apps/shovey', '/kryon-apps/arcade/games/arcade.shovey/records')
    body = body[:body.index("  console.log('Pip artwork")]

    setup = (ROOT / 'tests/web_driver.mjs').read_text()
    setup = setup[setup.index('`')+1:setup.rindex('`')]
    fixture = subprocess.check_output([str(ROOT / 'build/guide-test/native'), '74'], text=True)
    stationary = test[test.index('function stationaryCampaign'):test.index('const profile =')]
    prelude = """const assert=(ok,message)=>{if(!ok)throw Error(message)};
assert.equal=(a,b,m)=>assert(a===b,m||'equality failed');
assert.deepEqual=(a,b,m)=>assert(JSON.stringify(a)===JSON.stringify(b),m||'deep equality failed');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));let sequence=0;
"""
    campaign = json.loads((ROOT / 'levels/approved.json').read_text())
    config = dict(fixture=fixture, levelOneSolution=campaign['levels'][0]['solution'],
                  mapArt=world_map_art(),
                  driverSetup=setup, target=f'http://127.0.0.1:{server.server_port}/?play')
    prelude += ''.join('const '+k+'='+json.dumps(v)+';' for k,v in config.items()) + stationary
    # Execute the CI server's actual MIME expressions in Chromium: root
    # navigation must remain HTML while chunk files must remain binary.
    server_source = (ROOT/'tests/web_release_test.mjs').read_text()
    types = re.search(r"const types = (.*?);", server_source).group(1)
    content_type = re.search(r"response.setHeader\('Content-Type', (.*?)\);", server_source).group(1)
    prelude += 'const types='+types+';const mime=path=>('+content_type+');'
    for path, expected in (('/', 'text/html'), ('/index.html', 'text/html'),
                           ('/runtime.data.part-0000', 'application/octet-stream'),
                           ('/runtime.data.json', 'application/json'), ('/runtime.js', 'text/javascript'),
                           ('/runtime.wasm', 'application/wasm')):
        prelude += 'assert.equal(mime('+json.dumps(path)+'),'+json.dumps(expected)+');'
    prelude += 'const socket=new WebSocket('+json.dumps(game['webSocketDebuggerUrl'])+');await new Promise(resolve=>socket.addEventListener("open",resolve,{once:true}));'
    receipt = json.loads((WEB / 'arcade.json').read_text())
    local = receipt.get('local_bundles', {})
    files = [('Module.getPreloadedPackage()', json.loads((WEB / 'runtime.data.json').read_text())['sha256']),
             ("Module.FS.readFile('/app.zx/shovey.zx')" if local else "Module.FS.readFile('/app.zx')", receipt['sha256'])]
    for child in receipt['children']:
        if child['id'] in local:
            files.append(('Module.FS.readFile(' + json.dumps('/app.zx/' + local[child['id']]) + ')', child['sha256']))
    extra = """
    for (const [file, expected] of EXPECTED_FILES) {
      const digestResult = await call('Runtime.evaluate', {awaitPromise:true, returnByValue:true, expression:`crypto.subtle.digest('SHA-256', ${file}).then(b=>Array.from(new Uint8Array(b)).map(v=>v.toString(16).padStart(2,'0')).join(''))`});
      assert(!digestResult.exceptionDetails, 'Could not read packaged bytes: ' + file);
      assert.equal(digestResult.result.value, expected, 'Emscripten package bytes changed: ' + file);
    }
    for (const mode of ['missing','html','truncated','corrupt','path']) {
      await fetch(new URL('__test?mode=' + mode, target));
      await call('Page.reload');
      await wait(()=>evaluate(`document.querySelector('#loading').classList.contains('error')`), 'No failure screen: '+mode);
      assert(await evaluate(`!document.querySelector('script[src*=\"runtime.js\"]') && !Module.FS`), 'Runtime started with damaged data: '+mode);
    }
    socket.close();return 'PASS: exact released collection and game data; guest modals; external network blocked; replay/map; missing/HTML/truncated/corrupt/path failures';
""".replace('EXPECTED_FILES', json.dumps(files))
    expression = '(async()=>{'+prelude+body+extra+'})()'
    result = call('Runtime.evaluate', dict(expression=expression, awaitPromise=True, returnByValue=True, timeout=240000))
    if 'exceptionDetails' in result:
        diagnostic = call('Runtime.evaluate', dict(awaitPromise=True, returnByValue=True,
            expression="({nodes:globalThis.shoveyLastTree?.filter(n => n.visible).slice(-40).map(n => ({key:n.key,role:n.role,label:n.label})),console:globalThis.shoveyBrowserConsole})"))
        print('Browser diagnostic:', diagnostic.get('result', {}).get('value'), flush=True)
        state = call('Runtime.evaluate', dict(awaitPromise=True, returnByValue=True, expression="globalThis.shoveyTestEvaluate?.('({failed:Module.arcadeFailed,ready:Module.profileReady,exit:Module.EXITSTATUS})')"))
        print('Browser runtime:', state.get('result', {}).get('value'), flush=True)
    assert 'exceptionDetails' not in result, result
    print(result['result']['value'], flush=True)
finally:
    if connection: connection.close()
    import signal
    if browser.poll() is None: os.killpg(browser.pid, signal.SIGTERM)
    try: browser.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(browser.pid, signal.SIGKILL); browser.wait()
    server.shutdown(); server.server_close(); log.close()
    shutil.rmtree(PROFILE)
