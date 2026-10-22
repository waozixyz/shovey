#!/usr/bin/env python3
"""Build, verify and publish the exact approved campaign through Arcade's node app."""
import argparse
import contextlib
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


def publication_status():
    campaign = json.loads((ROOT / 'levels/approved.json').read_text())
    pending = campaign.get('pending', {})
    if pending:
        return f'Level {min(map(int, pending))} queued. Approve {len(campaign["levels"]) + 1}.'
    summary = ROOT / 'backup/editor-drafts/update-all-summary.json'
    if summary.exists():
        skipped = json.loads(summary.read_text()).get('unproven_boards', {})
        remaining = 0
        for number, digest in skipped.items():
            draft = ROOT / f'backup/editor-drafts/{int(number):03}.hex'
            published = ROOT / f'backup/editor-drafts/{int(number):03}.published'
            if draft.exists() and hashlib.sha256(draft.read_text().strip().encode()).hexdigest() == digest and (
                    not published.exists() or published.read_text().strip() != draft.read_text().strip()):
                remaining += 1
        if remaining:
            return f'Published · {remaining} not updated'
    return 'Published'


def record_published(receipt):
    boards = receipt.get('approved_boards')
    if boards is None and receipt['approved_sha256'] == fingerprint():
        levels = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
        boards = [''.join(level['cells'] + level['tiles'] + level['decorations']) for level in levels]
    for number, board in enumerate(boards or [], 1):
        atomic(STATE / f'{number:03}.published', board)


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


def release_publisher(arcade):
    apps = Path(subprocess.check_output([str(arcade / 'scripts/ziran.sh'), 'pkg', 'path', 'apps'], cwd=arcade, text=True).strip())
    spec = importlib.util.spec_from_file_location('node_release', apps / 'scripts/node_release.py')
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    return publisher


def complete_release(config, receipt, output):
    """Resume the exact checked artifact, even after an uncertain upload."""
    arcade = Path(config['arcade']).resolve(strict=True)
    store = ROOT / 'build/approved-releases'
    release = json.loads((store / 'inbe.arcade/latest-v2.json').read_text())
    artifact = release['artifacts'][0]
    payload = store / 'inbe.arcade' / (artifact['sha256'] + '.zib')
    if (release['version'] != receipt['versions']['arcade'] or artifact['sha256'] != receipt['sha256'] or
            payload.stat().st_size != artifact['size'] or hashlib.sha256(payload.read_bytes()).hexdigest() != artifact['sha256']):
        raise ValueError('The checked release artifact changed; no upload was attempted')
    publisher = release_publisher(arcade)
    origin = 'https://api.waozi.xyz'
    # Use Apps' existing public downloader and its normal User-Agent. A
    # server-side urllib request was denied even after a successful upload.
    public = publisher.served_release(origin, 'inbe.arcade')
    if public != release:
        target, remote_store = config['ssh_target'], config['remote_store']
        ssh = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', target]
        inspect_code = "import pathlib,sys; p=pathlib.Path(sys.argv[1])/'inbe.arcade/latest-v2.json'; print(p.read_text() if p.exists() else '{}')"
        served = json.loads(subprocess.check_output([*ssh, shlex.join(['python3', '-c', inspect_code, remote_store])], text=True))
        if served != release:
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
            status('Publishing…')
            publisher.publish_node_app(store, 'arcade', target, remote_store)
    status('Verifying…')
    with contextlib.redirect_stdout(output):
        publisher.verify_node_app(store, 'arcade', origin)
    receipt.update(phase='published', release=release)
    atomic(ROOT / 'backup/approved-publication.json', json.dumps(receipt, indent=2) + '\n')
    if config.get('install_local') and not receipt.get('local_installed'):
        built = arcade / 'build/arcade.zib'
        if hashlib.sha256(built.read_bytes()).hexdigest() != artifact['sha256']:
            raise ValueError('The local build changed after checking; the published release was preserved')
        # All release gates already passed for these outputs. Installation
        # must use them rather than silently rebuilding a different artifact.
        subprocess.run(['make', '-o', 'all', 'install'], cwd=arcade, stdout=output, stderr=subprocess.STDOUT, check=True)
        receipt['local_installed'] = True
    receipt['phase'] = 'verified'
    atomic(ROOT / 'backup/approved-publication.json', json.dumps(receipt, indent=2) + '\n')
    record_published(receipt)
    status(publication_status())


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
                if prior.get('approved_sha256') == approved_hash and prior.get('phase') in ('uploading', 'published'):
                    status('Updating…')
                    complete_release(config, prior, output)
                    if fingerprint() == approved_hash:
                        return 0
                    continue
                if not force and prior.get('approved_sha256') == approved_hash and prior.get('phase') == 'verified':
                    record_published(prior)
                    status(publication_status())
                    return 0
                ledger = json.loads((arcade / 'apps/versions.json').read_text())['node_apps']
                if prior.get('approved_sha256') == approved_hash and prior.get('phase') != 'verified':
                    versions = prior['versions']
                else:
                    versions = {name: next_version(ledger[name]['version']) for name in ('arcade', 'shovey', 'shovey-editor')}
                receipt = dict(approved_sha256=approved_hash, approved_levels=len(approved), versions=versions, phase='building',
                               approved_boards=[''.join(level['cells'] + level['tiles'] + level['decorations']) for level in approved])
                atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                status("Updating…")
                changelog(ROOT / 'src/CHANGELOG.md', versions['shovey'],
                          f'- Play the approved Classic campaign through level {len(approved)}.\n- Animals and fish choose their own directions from their first step and wander through open spaces.\n- Keep your progress and use the integrated level editor.', True)
                changelog(ROOT / 'src/editor/CHANGELOG.md', versions['shovey-editor'],
                          '- Animals and fish wander independently when testing Classic levels.\n- Create Classic or Island levels; story examples follow the approved Classic campaign.', True)
                changelog(arcade / 'CHANGELOG.md', versions['arcade'],
                          f'- Shovey includes approved Classic levels 1–{len(approved)}.\n- Animals and fish choose independent movement directions, including their first step.\n- Existing Shovey saves and completed levels are retained.')
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
                status('Checking…')
                private = [
                    'env', '-u', 'DISPLAY', '-u', 'WAYLAND_DISPLAY', '-u', 'XAUTHORITY', '-u', 'DBUS_SESSION_BUS_ADDRESS',
                    '-u', 'SESSION_MANAGER', 'YUE_DESKTOP_RECOVERY=0', 'SDL_AUDIODRIVER=dummy',
                    'xvfb-run', '-a', '-n', '400', '-s', '-screen 0 1600x1100x24']
                run([*private, 'python3', arcade / 'tests/collection_ui_test.py', '--binary', arcade / 'build/arcade', '--inbe-source', inbe], arcade)
                run([*private, 'python3', arcade / 'tests/shovey_standalone_ui_test.py', '--binary', arcade / 'build/shovey', '--inbe-source', inbe], arcade)
                run([*private, 'python3', ROOT / 'tests/inbe_navigation_ui_test.py', '--binary', inbe_binary,
                     '--inbe-source', inbe, '--bundle', arcade / 'build/arcade.zib'])
                if fingerprint() != approved_hash:
                    status('Updating…')
                    continue
                bundle = arcade / 'build/arcade.zib'
                receipt.update(phase='checked', sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                               checks=['approved routes', 'release boundary and saves', 'assets', 'Arcade UI', 'standalone Shovey UI', 'Inbe UI'])
                atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                publisher = release_publisher(arcade)
                store = ROOT / 'build/approved-releases'
                publisher.stage_node_app(store, 'arcade', Path(config['key']), config['key_id'],
                    inbe / 'apps/publishers.json', ledger_path=arcade / 'apps/versions.json', bundle_directory=arcade / 'build')
                receipt['phase'] = 'uploading'
                atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                complete_release(config, receipt, output)
                if fingerprint() == approved_hash:
                    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true', help='Ship updated software for the already approved campaign')
    arguments = parser.parse_args()
    try:
        raise SystemExit(main(arguments.force))
    except Exception as error:
        status('Update failed. Retry.')
        with (ROOT / 'backup/approved-publication.log').open('a') as log:
            log.write(type(error).__name__ + ': ' + str(error) + '\n')
        raise SystemExit(1)
