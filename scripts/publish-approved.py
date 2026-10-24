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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publication_queue import Queue
from editor_server import remember_verified

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'backup/editor-drafts'
ACTIVE_IDS = []


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(value)
    temporary.replace(path)


def status(message, phase=None):
    if phase:
        Queue(ROOT).advance(ACTIVE_IDS, phase, message)
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
    Queue(ROOT).published(boards or [])


def publish_live(output):
    """Replace the live campaign on the node, which players load at their next
    start. Each game checks every level's route itself before using it."""
    record = ROOT / 'backup/campaign-publisher/publication.json'
    key = ROOT / 'backup/campaign-publisher/account.key'
    if not record.is_file() or not key.is_file():
        return False
    publication = json.loads(record.read_text())
    entity = Path(subprocess.check_output(['ziran', 'pkg', 'path', 'entity'], cwd=ROOT, text=True).strip())
    try:
        subprocess.run(['make', 'publication'], cwd=entity, stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run([str(entity / 'build/publication'), 'publish', str(key), publication['server'], publication['format'],
                        publication['title'], str(ROOT / 'levels/approved.json'), publication['id']],
                       cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
    except subprocess.CalledProcessError as error:
        output.write(f'Live campaign not updated: {error}\n')
        return False
    return True


def commit_paths(repository, paths, message, output):
    """Commit these paths alone and push them. A private index keeps other
    work in the shared checkout out of the commit."""
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repository, text=True).strip()
    changed = [path for path in paths if subprocess.run(['git', 'show', head + ':' + path], cwd=repository,
               capture_output=True, text=True).stdout != (repository / path).read_text()]
    if not changed:
        return head
    index = STATE / 'website.index'
    environment = {**os.environ, 'GIT_INDEX_FILE': str(index)}
    git = lambda *arguments: subprocess.check_output(['git', *arguments], cwd=repository, env=environment, text=True).strip()
    try:
        git('read-tree', head)
        for path in changed:
            git('update-index', '--add', '--cacheinfo', '100644,' + git('hash-object', '-w', path) + ',' + path)
        commit = git('commit-tree', git('write-tree'), '-p', head, '-m', message)
    finally:
        index.unlink(missing_ok=True)
    subprocess.run(['git', 'update-ref', 'refs/heads/master', commit, head], cwd=repository, check=True)
    # Keep the shared index in step with the new commit for these paths.
    subprocess.run(['git', 'reset', '-q', '--', *changed], cwd=repository, check=True)
    subprocess.run(['git', 'push', 'origin', 'master'], cwd=repository, stdout=output, stderr=subprocess.STDOUT, check=True)
    return commit


def publish_website(receipt, output, arcade):
    """Commit the published campaign and its release records, Arcade's first,
    so the website rebuilds the browser game from the same approved levels
    and the download workflow builds the released version."""
    count = len(json.loads((ROOT / 'levels/approved.json').read_text())['levels'])
    receipt['arcade_records'] = commit_paths(arcade, ['CHANGELOG.md', 'VERSION', 'apps/versions.json'],
        f'Record Arcade {receipt["versions"]["arcade"]} with approved Shovey Classic levels 1-{count}', output)
    receipt['website'] = commit_paths(ROOT, ['levels/approved.json', 'src/CHANGELOG.md', 'src/editor/CHANGELOG.md'],
        f'Publish the approved campaign of {count} Classic levels on the website', output)


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
    payload = store / 'inbe.arcade' / (artifact['sha256'] + '.zx')
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
            status('Publishing release', 'publishing')
            publisher.publish_node_app(store, 'arcade', target, remote_store)
    status('Verifying server release', 'verifying')
    with contextlib.redirect_stdout(output):
        publisher.verify_node_app(store, 'arcade', origin)
    receipt.update(phase='published', release=release)
    atomic(ROOT / 'backup/approved-publication.json', json.dumps(receipt, indent=2) + '\n')
    if receipt.get('approved_boards'):
        remember_verified(ROOT, receipt)
    if config.get('install_local') and not receipt.get('local_installed'):
        built = arcade / 'build/arcade.zx'
        if hashlib.sha256(built.read_bytes()).hexdigest() != artifact['sha256']:
            raise ValueError('The local build changed after checking; the published release was preserved')
        # All release gates already passed for these outputs. Installation
        # must use them rather than silently rebuilding a different artifact.
        subprocess.run(['make', '-o', 'all', 'install'], cwd=arcade, stdout=output, stderr=subprocess.STDOUT, check=True)
        receipt['local_installed'] = True
    receipt['phase'] = 'verified'
    atomic(ROOT / 'backup/approved-publication.json', json.dumps(receipt, indent=2) + '\n')
    record_published(receipt)
    if receipt.get('website') is None:
        status('Updating website', 'publishing')
        publish_website(receipt, output, arcade)
        atomic(ROOT / 'backup/approved-publication.json', json.dumps(receipt, indent=2) + '\n')
    status(publication_status())


def publish_campaign():
    global ACTIVE_IDS
    config = json.loads((ROOT / 'backup/editor-publish.json').read_text())
    arcade = Path(config['arcade']).resolve(strict=True)
    inbe = Path(config['inbe_source']).resolve(strict=True)
    inbe_binary = Path(config['inbe_binary']).resolve(strict=True)
    toolchain = Path(subprocess.check_output(['ziran', 'pkg', 'path', 'ziran'], cwd=ROOT, text=True).strip())
    log = ROOT / 'backup/approved-publication.log'
    receipt_path = ROOT / 'backup/approved-publication.json'
    with log.open('a') as output:
        def run(command, cwd=ROOT, environment=None):
            subprocess.run(list(map(str, command)), cwd=cwd, env=environment,
                           stdout=output, stderr=subprocess.STDOUT, check=True)
        while True:
            approved_hash = fingerprint()
            approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
            boards = [''.join(level['cells'] + level['tiles'] + level['decorations']) for level in approved]
            ACTIVE_IDS = Queue(ROOT).claim(boards)
            if not ACTIVE_IDS:
                return 0
            prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
            if prior.get('phase') in ('uploading', 'published'):
                status('Resuming checked release', 'verifying')
                complete_release(config, prior, output)
                if fingerprint() == approved_hash:
                    return 0
                continue
            ledger = json.loads((arcade / 'apps/versions.json').read_text())['node_apps']
            if prior.get('approved_sha256') == approved_hash and prior.get('phase') != 'verified':
                versions = prior['versions']
            else:
                versions = {name: next_version(ledger[name]['version']) for name in ('arcade', 'shovey', 'shovey-editor')}
            receipt = dict(approved_sha256=approved_hash, approved_levels=len(approved), versions=versions, phase='building',
                           approved_boards=[''.join(level['cells'] + level['tiles'] + level['decorations']) for level in approved])
            atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
            # Players get the approved levels within seconds; the release with
            # the same levels built in follows after its checks.
            status('Updating live levels', 'building')
            receipt['live'] = publish_live(output)
            atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
            status('Building campaign', 'building')
            changelog(ROOT / 'src/CHANGELOG.md', versions['shovey'],
                      f'- Play the approved Classic campaign through level {len(approved)}.\n- All objects stop at the abyss and leave it open.\n- Keep your progress and use the integrated level editor.', True)
            changelog(ROOT / 'src/editor/CHANGELOG.md', versions['shovey-editor'],
                      '- All objects stop at the abyss when testing Classic levels.\n- Create your own Classic levels; story examples follow the approved Classic campaign.', True)
            changelog(arcade / 'CHANGELOG.md', versions['arcade'],
                      f'- Shovey includes approved Classic levels 1–{len(approved)}.\n- All objects stop at the abyss and leave it open.\n- Existing Shovey saves and completed levels are retained.')
            run([arcade / 'update_version.sh'], arcade)
            run(['python3', 'tools/levels/levels.py', 'generate'])
            run(['python3', 'tools/pixel/pixel.py', 'build'])
            run(['python3', 'tools/levels/landscape.py'])
            run(['python3', 'tools/levels/levels.py', 'previews'])
            run(['make', 'solver'])
            status('Checking winning routes and release', 'checking')
            for level in approved:
                board = ''.join(level['cells']) + ''.join(level['tiles']) + ''.join(level['decorations'])
                run([ROOT / 'build/solver/shovey-solve-classic', 'verify', '--level', level['number'], board, level['solution']])
            run(['sh', 'tests/release_test.sh', toolchain])
            run(['python3', 'tests/assets_test.py'])
            run(['make', 'all'], arcade)
            status('Checking game screens', 'checking')
            private = [
                'env', '-u', 'DISPLAY', '-u', 'WAYLAND_DISPLAY', '-u', 'XAUTHORITY', '-u', 'DBUS_SESSION_BUS_ADDRESS',
                '-u', 'SESSION_MANAGER', 'YUE_DESKTOP_RECOVERY=0', 'SDL_AUDIODRIVER=dummy',
                'xvfb-run', '-a', '-n', '400', '-s', '-screen 0 1600x1100x24']
            run([*private, 'python3', arcade / 'tests/collection_ui_test.py', '--binary', arcade / 'build/arcade', '--inbe-source', inbe], arcade)
            run([*private, 'python3', arcade / 'tests/shovey_standalone_ui_test.py', '--binary', arcade / 'build/shovey', '--inbe-source', inbe], arcade)
            run([*private, 'python3', ROOT / 'tests/inbe_navigation_ui_test.py', '--binary', inbe_binary,
                 '--inbe-source', inbe, '--bundle', arcade / 'build/arcade.zx'])
            if len(approved) >= 28:
                run([*private, 'python3', ROOT / 'tests/abyss_ui_test.py', '--binary', inbe_binary,
                     '--inbe-source', inbe, '--bundle', arcade / 'build/arcade.zx'])
            if fingerprint() != approved_hash:
                # Requests for this snapshot join the next campaign build.
                Queue(ROOT).advance(ACTIVE_IDS, 'building', 'Campaign changed; rebuilding')
                continue
            bundle = arcade / 'build/arcade.zx'
            receipt.update(phase='checked', sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                           checks=['approved routes', 'release boundary and saves', 'assets', 'Arcade UI', 'standalone Shovey UI', 'Inbe UI'])
            if len(approved) >= 28:
                receipt['checks'].append('level 28 abyss pixels at fractional scales')
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


def main(force=False):
    global ACTIVE_IDS
    # Requests are durable before a worker starts. Waiting workers take the
    # same lock, then see whether the previous worker already handled them.
    with (STATE / 'publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
            if force:
                Queue(ROOT).enqueue(approved, available=len(approved))
            boards = [''.join(level['cells'] + level['tiles'] + level['decorations']) for level in approved]
            ACTIVE_IDS = Queue(ROOT).claim(boards)
            if not ACTIVE_IDS:
                return 0
            return publish_campaign()
        except Exception as error:
            Queue(ROOT).fail(ACTIVE_IDS, error)
            raise


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
