#!/usr/bin/env python3
"""Real web win and reload regression; Python stdlib/CDP, no Node or live browser.

Run through build-queue. --web-root is an explicitly prepared private fixture
with the current web entry and its browser host. --collection supplies a
matching normal player collection/receipt to a reused collection host.
Never seeds progress; host and artifact provenance are recorded separately.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'work/web-result-runtime-test'


class CDP:
    """Small synchronous WebSocket transport for the private CDP endpoint."""
    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=30)
        nonce = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        response = b''
        while not response.endswith(b'\r\n\r\n'):
            response += self.sock.recv(1)
        assert b' 101 ' in response, response[:300]
        accept = base64.b64encode(hashlib.sha1((nonce + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        assert accept.lower() in response.lower()
        self.sequence = 0
        self.errors = []
        self.console = []

    def exact(self, size):
        result = bytearray()
        while len(result) < size:
            chunk = self.sock.recv(size - len(result))
            if not chunk:
                raise RuntimeError('Private CDP socket closed')
            result.extend(chunk)
        return bytes(result)

    def send(self, value):
        data = json.dumps(value).encode()
        mask = os.urandom(4)
        size = len(data)
        header = bytes([0x81, 0x80 | size]) if size < 126 else (bytes([0x81, 0xfe]) + struct.pack('!H', size) if size < 65536 else bytes([0x81, 0xff]) + struct.pack('!Q', size))
        self.sock.sendall(header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def receive(self):
        payload = bytearray()
        while True:
            a, b = self.exact(2)
            size = b & 127
            if size == 126:
                size = struct.unpack('!H', self.exact(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self.exact(8))[0]
            assert size < 16 * 1024 * 1024
            mask = self.exact(4) if b & 128 else None
            chunk = self.exact(size)
            if mask:
                chunk = bytes(c ^ mask[i % 4] for i, c in enumerate(chunk))
            assert a & 15 in (0, 1), ('Unexpected WebSocket opcode', a & 15)
            payload.extend(chunk)
            if a & 128:
                return json.loads(payload)

    def call(self, method, **params):
        self.sequence += 1
        current = self.sequence
        self.send(dict(id=current, method=method, params=params))
        while True:
            message = self.receive()
            if message.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(str(message['params'])[:1500])
            if message.get('method') == 'Runtime.consoleAPICalled':
                self.console.append(str(message['params'].get('args', []))[:500])
                self.console = self.console[-15:]
            if message.get('id') == current:
                assert 'error' not in message, message
                return message.get('result', {})

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        assert 'exceptionDetails' not in result, result
        return result.get('result', {}).get('value')

    def wait(self, expression, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.evaluate(expression):
                return
            time.sleep(.1)
        raise AssertionError(('Timed out', expression, self.errors, self.console))


class Game:
    def __init__(self, cdp, record_root):
        self.cdp = cdp
        self.record_root = record_root
        self.serial = 0
        self.nodes = []

    def tree(self):
        self.serial += 1
        self.cdp.evaluate('Module.FS.writeFile("/tmp/test-driver/command", ' + json.dumps(f'{self.serial}\ttree\n') + ')')
        try:
            self.cdp.wait('Module.FS.analyzePath("/tmp/test-driver/reply").exists', 15)
        except AssertionError:
            print('HOST STATE', self.cdp.evaluate('({text:document.body.innerText.slice(0,1500),profileReady:Module.profileReady,storage:Module.FS.readdir("/kryon-apps"), canvas:[Module.canvas.width,Module.canvas.height], root:Module.FS.readdir("/"), app:Module.FS.stat("/app.zx").size,driver:Module.FS.readdir("/tmp/test-driver")})'), flush=True)
            raise
        reply = json.loads(self.cdp.evaluate('Module.FS.readFile("/tmp/test-driver/reply", {encoding:"utf8"})'))
        self.cdp.evaluate('Module.FS.unlink("/tmp/test-driver/reply")')
        assert reply['ok'], reply
        self.nodes = reply['nodes']
        return self.nodes

    def find(self, label=None, key=None):
        return next((n for n in self.tree() if (label is None or n.get('label') == label) and (key is None or n.get('key') == key) and n.get('visible', True)), None)

    def wait(self, label=None, key=None, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            node = self.find(label, key)
            if node:
                return node
            time.sleep(.1)
        raise AssertionError(('Missing UI node', label, key, [n.get('label') for n in self.nodes]))

    def press(self, label=None, key=None):
        n = self.wait(label, key)
        assert n.get('role') == 'button' or n.get('kind') == 'button', n
        assert n.get('enabled', True), n
        x, y = n['x'] + n['width'] / 2, n['y'] + n['height'] / 2
        self.cdp.call('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y, button='left', buttons=1, clickCount=1)
        time.sleep(.08)
        self.cdp.call('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y, button='left', buttons=0, clickCount=1)
        time.sleep(.25)

    def key(self, direction):
        key, code = [('ArrowLeft', 37), ('ArrowUp', 38), ('ArrowRight', 39), ('ArrowDown', 40)][int(direction)]
        for event in ('keyDown', 'keyUp'):
            self.cdp.call('Input.dispatchKeyEvent', type=event, key=key, code=key, windowsVirtualKeyCode=code)

    def read(self, name):
        return self.cdp.evaluate('Module.FS.readFile(' + json.dumps(self.record_root + '/' + name) + ', {encoding:"utf8"})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-root', type=Path, required=True)
    parser.add_argument('--collection', type=Path, help='Stable normal fixture directory containing shovey.zx and shovey.json; no builds')
    parser.add_argument('--artifact-provenance', type=Path, help='Saved build receipt and compile identity, separate from runtime checkout')
    parser.add_argument('--record-root', default='/kryon-apps/shovey')
    parser.add_argument('--startup-timeout', type=int, default=90)
    parser.add_argument('--startup-only', action='store_true', help='Diagnostic control only; does not verify results')
    parser.add_argument('--chromium', default=shutil.which('chromium'))
    args = parser.parse_args()
    subprocess.run(['git', 'check-ignore', '-q', str(OUT)], cwd=ROOT, check=True)
    OUT.mkdir(parents=True, exist_ok=True)
    web = args.web_root.resolve()
    route = json.loads((ROOT / 'levels/approved.json').read_text())['levels'][0]['solution']
    assert len(route) == 51 and set(route) <= set('0123'), route
    sources = sorted((ROOT / 'src').rglob('*.zi')) + sorted((ROOT / 'src/locales').glob('*.txt')) + [ROOT / 'ziran.lock', ROOT / 'levels/approved.json']
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    receipt = dict(command=['build-queue', '--', 'python3', *(__import__('sys').argv)], runtime_checkout_start=hashes,
                   browser=subprocess.check_output([args.chromium, '--version'], text=True).strip(), limits='localhost only, synthetic profile, no screenshots, no accounts, no Node; unchanged reusable browser host')
    receipt['source_identity_note'] = 'Runtime checkout hashes are observations, not the compile inputs of the supplied artifact; concurrent map work may change them.'
    if args.artifact_provenance:
        receipt['artifact_provenance'] = json.loads(args.artifact_provenance.read_text())
    receipt['artifacts'] = {str(p.relative_to(web)): digest(p) for p in web.iterdir() if p.is_file()}
    collection_files = {}
    if args.collection:
        collection = args.collection.resolve()
        collection_files = {'/__test_collection.zx': collection / 'shovey.zx',
                            '/__test_receipt.json': collection / 'shovey.json'}
        metadata = json.loads(collection_files['/__test_receipt.json'].read_text())
        assert metadata['id'] == 'arcade.shovey-player', metadata['id']
        with collection_files['/__test_collection.zx'].open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == metadata['sha256'], 'Collection receipt digest mismatch'
        receipt['collection'] = {str(path): digest(path) for path in collection_files.values()}
        receipt['collection_metadata'] = metadata
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(web), **kw)
        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in collection_files:
                source = collection_files[path]
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(source.stat().st_size))
                self.end_headers()
                with source.open('rb') as stream:
                    shutil.copyfileobj(stream, self.wfile)
                return
            if args.collection and path in ('/', '/index.html'):
                page = (web / 'index.html').read_text()
                assert page.count("bundle('runtime.data')") == 1
                assert page.count('Module.arcadeReceipt = loaded[0];') == 1
                page = page.replace("bundle('runtime.data')", "bundle('runtime.data'), fetch('/__test_collection.zx').then(r=>r.arrayBuffer()), fetch('/__test_receipt.json').then(r=>r.text())")
                page = page.replace('Module.arcadeReceipt = loaded[0];', "Module.arcadeReceipt = loaded[3]; Module.onRuntimeInitialized = function(){Module.FS.writeFile('/app.zx',new Uint8Array(loaded[2]));};")
                data = page.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = cdp = None
    try:
        with tempfile.TemporaryDirectory(prefix='profile-', dir=OUT) as tmp, (OUT / 'chromium.log').open('w') as log:
            env = dict(os.environ, YUE_DESKTOP_RECOVERY='0')
            for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY', 'DESKTOP_SESSION', 'XDG_SESSION_ID', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP'):
                env.pop(key, None)
            receipt['private_profile'] = tmp
            browser = subprocess.Popen([args.chromium, '--headless=new', '--no-sandbox', '--disable-gpu', '--mute-audio', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0', '--user-data-dir=' + tmp, '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1', 'about:blank'], env=env, stdout=log, stderr=log, start_new_session=True)
            receipt['browser_pid'] = browser.pid
            try:
                portfile = Path(tmp) / 'DevToolsActivePort'
                end = time.monotonic() + 30
                while not portfile.exists():
                    assert browser.poll() is None, ('Chromium exited', browser.returncode)
                    assert time.monotonic() < end, 'No private CDP endpoint'
                    time.sleep(.1)
                port = int(portfile.read_text().splitlines()[0])
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:
                    pages = json.load(response)
                cdp = CDP(next(p['webSocketDebuggerUrl'] for p in pages if p['type'] == 'page'))
                cdp.call('Runtime.enable')
                cdp.call('Page.enable')
                cdp.call('Network.enable')
                cdp.call('Network.setBlockedURLs', urls=['https://*', 'http://api.*', 'http://account.*'])
                # Same preRun hook as web_driver.mjs; game/storage are never stubbed.
                setup = (ROOT / 'tests/web_driver.mjs').read_text().split('`', 2)[1]
                cdp.call('Page.addScriptToEvaluateOnNewDocument', source=setup)
                cdp.call('Emulation.setDeviceMetricsOverride', width=400, height=800, deviceScaleFactor=1, mobile=True)
                url = f'http://127.0.0.1:{server.server_port}/'
                cdp.call('Page.navigate', url=url)
                cdp.wait('!!globalThis.Module?.FS?.analyzePath("/tmp/test-driver").exists', 90)
                cdp.wait('!!Module.profileReady || (!!Module.FS.analyzePath("/assets/shovey/catalog.json").exists && !!document.querySelector("#loading-screen.is-hidden"))', args.startup_timeout)
                game = Game(cdp, args.record_root)
                game.wait(label='Play', timeout=90)
                if args.startup_only:
                    receipt.update(result='CONTROL_STARTUP_PASS', canvas=cdp.evaluate('[Module.canvas.width,Module.canvas.height]'), nodes=len(game.tree()))
                    print('CONTROL PASS: private browser host initialized and actual UI driver answered; no new result proof',flush=True)
                    return
                if game.find(label='Download new levels when they come out?'):
                    game.press(label='Not now')
                game.press(label='Play')
                game.wait(key=20105)
                # No completion has been played or legacy rating invented.
                game.press(key=33001)
                game.wait(label='Level 1')
                initial = game.find(key=20910)
                assert initial is None, initial
                game.press(key=20122)
                end = time.monotonic() + 30
                while time.monotonic() < end:
                    if game.find(label='Download new levels when they come out?'):
                        game.press(label='Not now')
                    elif game.find(label='How do you want to move?'):
                        game.press(label='Swipe and tap')
                    elif game.find(label='Got it'):
                        game.press(label='Got it')
                    elif any(n.get('label', '').startswith('Level 1 / ') for n in game.tree()):
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError('Level 1 onboarding did not finish')
                time.sleep(1)
                for step, direction in enumerate(route, 1):
                    game.key(direction)
                    end = time.monotonic() + 5
                    while True:
                        text = game.read('local.campaign')
                        start = 1006 if text.startswith(('C5', 'C6')) else 179
                        recorded = int(text[start + 12:start + 20], 16)
                        if recorded >= step:
                            assert recorded == step, (step, recorded)
                            break
                        assert time.monotonic() < end, ('Move did not record', step, direction, recorded)
                        time.sleep(.05)
                    time.sleep(.2)
                for label in ('Level 1 complete', '★ ★ ★', 'Score: 1000 / 1000', 'Moves: 51'):
                    game.wait(label=label)
                time.sleep(2)
                game.wait(label='Level 1 complete')
                records = cdp.evaluate('Module.FS.readdir(' + json.dumps(args.record_root) + ').filter(n=>n.startsWith("local.result.") && n.endsWith(".1"))')
                assert len(records) == 1, records
                saved = json.loads(game.read(records[0]))
                assert saved['level'] == 1 and saved['moves'] == 51 and saved['owner'] == '', saved
                game.press(key=20905)
                assert not game.find(label='Level 1 complete')
                assert any(n.get('label', '').startswith('Level 2 / ') for n in game.tree())
                game.press(label='Levels')
                game.press(key=33001)
                best = game.wait(key=20910)['label']
                assert '★★★' in best and '1000' in best, best
                # Give the host's normal periodic IndexedDB flush time to run;
                # do not call syncfs ourselves or seed any record.
                time.sleep(4)
                cdp.call('Page.reload', ignoreCache=True)
                cdp.wait('!!globalThis.Module?.FS?.analyzePath("/tmp/test-driver").exists', 90)
                game.wait(label='Play', timeout=90)
                assert json.loads(game.read(records[0])) == saved
                game.press(label='Play')
                game.wait(key=20105)
                game.press(key=33001)
                after = game.wait(key=20910)['label']
                assert '★★★' in after and '1000' in after, after
                assert not cdp.errors, cdp.errors
                assert all(digest(Path(p)) == h for p,h in receipt.get('collection', {}).items()), 'Collection changed during runtime test'
                receipt.update(result='PASS', saved=saved, map_before=initial, map_after=best, map_after_reload=after, browser_errors=cdp.errors)
                print('PASS: actual web map-first, real 51-move win, 3 stars/1000, explicit Continue, local result and map best survive normal browser reload', flush=True)
            finally:
                if cdp:
                    try:
                        receipt['host_state'] = cdp.evaluate('({text:document.body.innerText.slice(0,2000),ready:Module.profileReady,files:Module.FS?.readdir("/"),storage:Module.FS?.analyzePath("/kryon-apps").exists?Module.FS.readdir("/kryon-apps"):[]})')
                    except Exception as diagnostic:
                        receipt['diagnostic_error'] = str(diagnostic)
                    cdp.sock.close()
                if browser and browser.poll() is None:
                    os.killpg(browser.pid, signal.SIGTERM)
                    try:
                        browser.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(browser.pid, signal.SIGKILL)
                        browser.wait(timeout=5)
    except BaseException as error:
        receipt.update(result='FAIL', failure=str(error), errors=cdp.errors if cdp else [], console=cdp.console if cdp else [])
        raise
    finally:
        receipt['runtime_checkout_end'] = {p: digest(ROOT / p) if (ROOT / p).exists() else None for p in hashes}
        receipt['runtime_checkout_changed'] = [p for p,h in hashes.items() if receipt['runtime_checkout_end'][p] != h]
        receipt['browser_reaped'] = browser is not None and browser.poll() is not None
        receipt['private_profile_removed'] = not Path(receipt.get('private_profile', '/nonexistent')).exists()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        (OUT / ('control-receipt.json' if args.startup_only else 'receipt.json')).write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
