#!/usr/bin/env python3
"""Build, verify and publish the exact approved campaign through Arcade's node app."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'backup/editor-drafts'


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(value)
    temporary.replace(path)


def status(message):
    atomic(STATE / 'publish-status', message[:240])
    try:
        print(message, flush=True)
    except BrokenPipeError:
        pass


def fingerprint():
    value = json.loads((ROOT / 'levels/approved.json').read_text())
    return hashlib.sha256(json.dumps(value['levels'], sort_keys=True).encode()).hexdigest()


def next_version(value):
    major, minor, patch = map(int, value.split('.'))
    return f'{major}.{minor}.{patch + 1}'


def changelog(path, version, notes, brackets=False):
    text = path.read_text()
    if re.search(r'^## \[?' + re.escape(version) + r'\]?\s', text, re.M):
        return
    date = time.strftime('%Y-%m-%d')
    heading = f'## [{version}] - {date}' if brackets else f'## {version}'
    first, rest = text.split('\n', 1)
    atomic(path, first + '\n\n' + heading + '\n\n' + notes + '\n' + rest.lstrip('\n'))


def main(force=False):
    config = json.loads((ROOT / 'backup/editor-publish.json').read_text())
    arcade = Path(config['arcade']).resolve(strict=True)
    inbe = Path(config['inbe_source']).resolve(strict=True)
    inbe_binary = Path(config['inbe_binary']).resolve(strict=True)
    toolchain = Path(subprocess.check_output(['ziran', 'pkg', 'path', 'ziran'], cwd=ROOT, text=True).strip())
    log = ROOT / 'backup/approved-publication.log'
    receipt_path = ROOT / 'backup/approved-publication.json'
    with (STATE / 'publish.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # The active worker rechecks the queue after each build.
        with log.open('a') as output:
            def run(command, cwd=ROOT, environment=None):
                subprocess.run(list(map(str, command)), cwd=cwd, env=environment,
                               stdout=output, stderr=subprocess.STDOUT, check=True)
            while True:
                approved_hash = fingerprint()
                approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
                prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
                if not force and prior.get('approved_sha256') == approved_hash and prior.get('phase') == 'verified':
                    status(f'Levels 1–{len(approved)} are live on the server. Island is disabled.')
                    return 0
                ledger = json.loads((arcade / 'apps/versions.json').read_text())['node_apps']
                if prior.get('approved_sha256') == approved_hash and prior.get('phase') != 'verified':
                    versions = prior['versions']
                else:
                    versions = {name: next_version(ledger[name]['version']) for name in ('arcade', 'shovey', 'shovey-editor')}
                receipt = dict(approved_sha256=approved_hash, approved_levels=len(approved), versions=versions, phase='building')
                atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                status(f'Approved through level {len(approved)}. Building the server update…')
                changelog(ROOT / 'src/CHANGELOG.md', versions['shovey'],
                          f'- Play the approved Classic campaign through level {len(approved)}.\n- Keep your progress while later levels are being edited.\n- Clearer animal directions, recessed green pressure buttons and quick portal travel.', True)
                changelog(ROOT / 'src/editor/CHANGELOG.md', versions['shovey-editor'],
                          '- Story levels follow the approved Classic campaign; Island stays unavailable while in development.', True)
                changelog(arcade / 'CHANGELOG.md', versions['arcade'],
                          f'- Shovey includes approved Classic levels 1–{len(approved)} with updated artwork and portal travel.\n- Island stays unavailable while its levels are being edited.\n- Existing Shovey saves and completed levels are retained.')
                run([arcade / 'update_version.sh'], arcade)
                run(['python3', 'tools/levels/levels.py', 'generate'])
                run(['python3', 'tools/pixel/pixel.py', 'build'])
                run(['python3', 'tools/levels/landscape.py'])
                run(['python3', 'tools/levels/levels.py', 'previews'])
                run(['make', 'solver'])
                for level in approved:
                    board = ''.join(level['cells']) + ''.join(level['tiles']) + ''.join(level['decorations'])
                    run([ROOT / 'build/solver/shovey-solve-classic', 'verify', '--level', level['number'], board, level['solution']])
                run(['sh', 'tests/release_test.sh', toolchain])
                run(['python3', 'tests/assets_test.py'])
                run(['make', 'all'], arcade)
                status('Checking the exact update in Arcade and Inner Breeze…')
                private = [
                    'env', '-u', 'DISPLAY', '-u', 'WAYLAND_DISPLAY', '-u', 'XAUTHORITY', '-u', 'DBUS_SESSION_BUS_ADDRESS',
                    '-u', 'SESSION_MANAGER', 'YUE_DESKTOP_RECOVERY=0', 'SDL_AUDIODRIVER=dummy',
                    'xvfb-run', '-a', '-n', '400', '-s', '-screen 0 1600x1100x24']
                run([*private, 'python3', arcade / 'tests/collection_ui_test.py', '--binary', arcade / 'build/arcade', '--inbe-source', inbe], arcade)
                run([*private, 'python3', arcade / 'tests/shovey_standalone_ui_test.py', '--binary', arcade / 'build/shovey', '--inbe-source', inbe], arcade)
                run([*private, 'python3', ROOT / 'tests/inbe_navigation_ui_test.py', '--binary', inbe_binary,
                     '--inbe-source', inbe, '--bundle', arcade / 'build/arcade.zib'])
                if fingerprint() != approved_hash:
                    status('A newer approval arrived; rebuilding before publishing.')
                    continue
                bundle = arcade / 'build/arcade.zib'
                receipt.update(phase='checked', sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                               checks=['approved routes', 'release boundary and saves', 'assets', 'Arcade UI', 'standalone Shovey UI', 'Inbe UI'])
                atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                apps = Path(subprocess.check_output([str(arcade / 'scripts/ziran.sh'), 'pkg', 'path', 'apps'], cwd=arcade, text=True).strip())
                spec = importlib.util.spec_from_file_location('node_release', apps / 'scripts/node_release.py')
                publisher = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(publisher)
                store = ROOT / 'build/approved-releases'
                release = publisher.stage_node_app(store, 'arcade', Path(config['key']), config['key_id'],
                    inbe / 'apps/publishers.json', ledger_path=arcade / 'apps/versions.json', bundle_directory=arcade / 'build')
                target, remote_store = config['ssh_target'], config['remote_store']
                ssh = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', target]
                # The installed receiver is the existing Inbe signed importer.
                # Root's deployment connection invokes that same restricted
                # receiver without changing SSH configuration or publisher keys.
                def upload(archive, unused_target, requested_store):
                    if requested_store != remote_store:
                        raise ValueError('The package store changed')
                    original = shlex.join(['inbe-packages', remote_store])
                    command = shlex.join(['env', 'SSH_ORIGINAL_COMMAND=' + original, 'python3',
                        '/opt/inbe-packages/package-release.py', '--receive-archive', '--store', remote_store,
                        '--publishers', '/opt/inbe-packages/publishers.json'])
                    with archive.open('rb') as stream:
                        subprocess.run([*ssh, command], stdin=stream, stdout=output, stderr=subprocess.STDOUT, check=True)
                publisher.upload = upload
                # Inspect first, so resuming a failed public verification never
                # replays an upload whose result was uncertain.
                inspect_code = "import pathlib,sys; p=pathlib.Path(sys.argv[1])/'inbe.arcade/latest-v2.json'; print(p.read_text() if p.exists() else '{}')"
                served = json.loads(subprocess.check_output([*ssh, shlex.join(['python3', '-c', inspect_code, remote_store])], text=True))
                if served != release:
                    status('Publishing the checked Arcade update…')
                    receipt['phase'] = 'uploading'
                    atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                    publisher.publish_node_app(store, 'arcade', target, remote_store)
                verify_code = """import json,sys,urllib.request,hashlib
expected=json.load(sys.stdin)
base='https://api.waozi.xyz/api/v2/packages/inbe.arcade'
with urllib.request.urlopen(base+'/latest?bucket=0',timeout=30) as r: actual=json.load(r)
assert actual==expected, 'Public metadata differs'
artifact=expected['artifacts'][0]
with urllib.request.urlopen(base+'/'+artifact['sha256']+'.zib',timeout=60) as r: payload=r.read(artifact['size']+1)
assert len(payload)==artifact['size'] and hashlib.sha256(payload).hexdigest()==artifact['sha256'], 'Public payload differs'
print('Exact signed Arcade metadata and payload verified at the public Waozi endpoint')
"""
                subprocess.run([*ssh, shlex.join(['python3', '-c', verify_code])], input=json.dumps(release).encode(), stdout=output, stderr=subprocess.STDOUT, check=True)
                receipt['phase'] = 'verified'
                receipt['release'] = release
                atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                if config.get('install_local'):
                    run(['make', 'install'], arcade)
                status(f'Levels 1–{len(approved)} are live on the server. Island is disabled.')
                if fingerprint() == approved_hash:
                    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true', help='Ship updated software for the already approved campaign')
    arguments = parser.parse_args()
    try:
        raise SystemExit(main(arguments.force))
    except Exception as error:
        status('The approved update failed. Press Update to retry; no new approval is needed.')
        with (ROOT / 'backup/approved-publication.log').open('a') as log:
            log.write(type(error).__name__ + ': ' + str(error) + '\n')
        raise SystemExit(1)
