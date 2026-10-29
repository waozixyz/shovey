#!/usr/bin/env python3
"""Publish the exact approved campaign: live at once, then as a checked Shovey
release that Shovey's Downloads workflow publishes and Arcade follows."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publication_queue import Queue

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'backup/editor-drafts'
ACTIVE_IDS = []
# The editor may run as a desktop service whose PATH lacks the user's own
# tools; ziran and the package scripts live in ~/.local/bin.
_local_bin = str(Path.home() / '.local/bin')
if _local_bin not in os.environ.get('PATH', '').split(os.pathsep):
    os.environ['PATH'] = _local_bin + os.pathsep + os.environ.get('PATH', '')


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


def project(value):
    """A repository the publisher config names. Projects moved into org
    folders (games/, apps/), so a path that no longer exists falls back to
    the same folder one level down."""
    path = Path(value)
    if path.exists():
        return path.resolve()
    org = ROOT.parents[1]
    if path.is_relative_to(org):
        relative = path.relative_to(org)
        for candidate in sorted(org.glob('*/' + str(relative))):
            return candidate.resolve()
    raise FileNotFoundError(f'{value} is missing; update backup/editor-publish.json')


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


def publish_live(output, campaign_path=None):
    """Replace the live campaign on the node, which players load at their next
    start. Each game checks every level's route itself before using it."""
    record = ROOT / 'backup/campaign-publisher/publication.json'
    key = ROOT / 'backup/campaign-publisher/account.key'
    if not record.is_file() or not key.is_file():
        return False
    publication = json.loads(record.read_text())
    entity = Path(subprocess.check_output(['ziran', 'pkg', 'path', 'entity'], cwd=ROOT, text=True).strip())
    # The node keeps documents of up to 256 KiB, so the published copy leaves
    # out approved.json's indentation; the games read either form.
    campaign = ROOT / 'backup/campaign-publisher/campaign.json'
    source = Path(campaign_path) if campaign_path is not None else ROOT / 'levels/approved.json'
    atomic(campaign, json.dumps(json.loads(source.read_text()), separators=(',', ':'),
                                ensure_ascii=False))
    subprocess.run(['make', 'publication'], cwd=entity, stdout=output, stderr=subprocess.STDOUT, check=True)
    answer = subprocess.run([str(entity / 'build/publication'), 'publish', str(key), publication['server'], publication['format'],
                             publication['title'], str(campaign), publication['id']],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output.write(answer.stdout)
    if answer.returncode != 0:
        # The screen checks expect the new campaign, so say why it is missing.
        reason = (answer.stdout.strip().splitlines() or ['no answer'])[-1]
        raise RuntimeError(f'Live campaign not updated ({campaign.stat().st_size} bytes): {reason}')
    return True


LIVE_MARK = ROOT / 'backup/campaign-publisher/live.sha256'


def publish_live_now():
    """Players load the approved campaign from the node at their next start.
    Every update uploads it first, before any release build and without
    waiting for a release that is still running. Returns whether the node
    now serves this campaign."""
    with (STATE / 'live.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        source = (ROOT / 'levels/approved.json').read_bytes()
        approved = json.loads(source)['levels']
        boards = [''.join(level['cells'] + level['tiles'] + level['decorations']) for level in approved]
        digest = hashlib.sha256(source).hexdigest()
        if LIVE_MARK.is_file() and LIVE_MARK.read_text().strip() == digest:
            Queue(ROOT).live_boards(boards)
            return True
        atomic(STATE / 'publish-status', 'Updating live levels')
        with (ROOT / 'backup/approved-publication.log').open('a') as output:
            try:
                live = publish_live(output)
            except Exception as error:
                Queue(ROOT).fail_waiting(boards, error)
                raise
        if live:
            atomic(LIVE_MARK, digest + '\n')
            Queue(ROOT).live_boards(boards)
        return live


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


def push_release(receipt, output):
    """Commit the approved campaign and its release records and push them.
    Shovey's Downloads workflow builds, checks and publishes that version,
    then starts Arcade's game update, so Arcade follows the release."""
    count = len(json.loads((ROOT / 'levels/approved.json').read_text())['levels'])
    receipt['release_commit'] = commit_paths(ROOT, ['levels/approved.json', 'src/CHANGELOG.md',
        'src/editor/CHANGELOG.md', 'version.json'],
        f'Release Shovey {receipt["versions"]["shovey"]} with approved Classic levels 1-{count}', output)


def current_version(changelog):
    """The newest numeric release a changelog names."""
    match = re.search(r'^## \[?([0-9]+\.[0-9]+\.[0-9]+)\]?', changelog.read_text(), re.M)
    if match is None:
        raise ValueError(f'{changelog} needs a numeric release entry')
    return match[1]


def next_version(value):
    major, minor, patch = map(int, value.split('.'))
    return f'{major}.{minor}.{patch + 1}'


def changelog(path, version, notes, brackets=False):
    text = path.read_text()
    if re.search(r'^## \[?' + re.escape(version) + r'\]?\s', text, re.M):
        return
    date = time.strftime('%Y-%m-%d')
    heading = f'## [{version}] - {date}' if brackets else f'## {version}'
    # Changes collected under Unreleased become this release's notes.
    unreleased = re.search(r'^## \[?Unreleased\]?[^\n]*$', text, re.M)
    if unreleased:
        atomic(path, text[:unreleased.start()] + heading + text[unreleased.end():])
        return
    first, rest = text.split('\n', 1)
    atomic(path, first + '\n\n' + heading + '\n\n' + notes + '\n' + rest.lstrip('\n'))


def released(version):
    """Whether GitHub has published this version's release."""
    answer = subprocess.run(['gh', 'release', 'view', 'v' + version, '--repo', 'waozixyz/shovey',
                             '--json', 'isDraft,tagName,url'], cwd=ROOT, capture_output=True, text=True)
    if answer.returncode != 0:
        return None
    release = json.loads(answer.stdout)
    return None if release['isDraft'] else release


def complete_release(config, receipt, output):
    """Wait until Shovey's Downloads workflow publishes the pushed version."""
    version = receipt['versions']['shovey']
    status('Releasing Shovey ' + version, 'publishing')
    deadline = time.monotonic() + 3 * 3600
    while (release := released(version)) is None:
        if time.monotonic() > deadline:
            raise RuntimeError(f'GitHub has not published Shovey {version}; see its Downloads workflow')
        time.sleep(60)
    receipt.update(phase='published', release=dict(tag=release['tagName'], url=release['url']))
    atomic(ROOT / 'backup/approved-publication.json', json.dumps(receipt, indent=2) + '\n')
    finish_release(config, receipt, output)


def finish_release(config, receipt, output):
    """After GitHub publishes the release: receipts and the local install."""
    if config.get('install_local') and not receipt.get('local_installed'):
        built = ROOT / 'build/player/shovey.zx'
        if hashlib.sha256(built.read_bytes()).hexdigest() != receipt['sha256']:
            raise ValueError('The local build changed after checking; the published release was preserved')
        # The checked player, installed as it was checked.
        subprocess.run(['make', '-o', 'player-linux', 'install'], cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, check=True)
        receipt['local_installed'] = True
    receipt['phase'] = 'verified'
    atomic(ROOT / 'backup/approved-publication.json', json.dumps(receipt, indent=2) + '\n')
    record_published(receipt)
    status(publication_status())


def publish_campaign():
    global ACTIVE_IDS
    config = json.loads((ROOT / 'backup/editor-publish.json').read_text())
    # Inner Breeze's checkout supplies the UI tests' driver.
    inbe = project(config['inbe_source'])
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
            if prior.get('phase') in ('pushed', 'published') and prior.get('release_commit'):
                status('Resuming checked release', 'verifying')
                complete_release(config, prior, output)
                if fingerprint() == approved_hash:
                    return 0
                continue
            if prior.get('approved_sha256') == approved_hash and prior.get('phase') != 'verified' and \
                    'arcade' not in prior.get('versions', {}):
                versions = prior['versions']
            else:
                versions = {name: next_version(current_version(ROOT / path)) for name, path in
                            (('shovey', 'src/CHANGELOG.md'), ('shovey-editor', 'src/editor/CHANGELOG.md'))}
            receipt = dict(approved_sha256=approved_hash, approved_levels=len(approved), versions=versions, phase='building',
                           approved_boards=[''.join(level['cells'] + level['tiles'] + level['decorations']) for level in approved])
            atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
            # Players get the approved levels within seconds; the release with
            # the same levels built in follows after its checks.
            status('Updating live levels', 'building')
            receipt['live'] = publish_live_now()
            atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
            if receipt['live']: Queue(ROOT).live(ACTIVE_IDS)
            # A hold (backup/editor-drafts/release-hold, its reason inside)
            # keeps releases off the node, such as while installed hosts
            # cannot read the bundle format this checkout builds.
            hold = STATE / 'release-hold'
            if hold.is_file() and receipt['live']:
                Queue(ROOT).hold(ACTIVE_IDS, hold.read_text().strip() or 'Release on hold')
                receipt['phase'] = 'held'
                atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
                return 0
            status('Building campaign', 'building')
            changelog(ROOT / 'src/CHANGELOG.md', versions['shovey'],
                      f'- Play the approved Classic campaign through level {len(approved)}.\n- All objects stop at the abyss and leave it open.\n- Keep your progress and use the integrated level editor.', True)
            changelog(ROOT / 'src/editor/CHANGELOG.md', versions['shovey-editor'],
                      '- All objects stop at the abyss when testing Classic levels.\n- Create your own Classic levels; story examples follow the approved Classic campaign.', True)
            run(['sh', ROOT / 'update_version.sh'])
            run(['python3', 'tools/levels/levels.py', 'generate'])
            run(['python3', 'tools/pixel/pixel.py', 'build'])
            run(['python3', 'tools/levels/landscape.py'])
            run(['python3', 'tools/levels/levels.py', 'previews'])
            run(['make', 'solver'])
            # Routes already proven for the exact same board and solver are
            # not replayed again; only new or changed levels are.
            proven_path = ROOT / 'backup/editor-drafts/proven-routes.json'
            proven = set(json.loads(proven_path.read_text())) if proven_path.exists() else set()
            solver = (ROOT / 'build/solver/fingerprint').read_text().strip() if (ROOT / 'build/solver/fingerprint').exists() else ''
            for level in approved:
                board = ''.join(level['cells']) + ''.join(level['tiles']) + ''.join(level['decorations'])
                proof = hashlib.sha256(f"{solver}:{level['number']}:{board}:{level['solution']}".encode()).hexdigest()
                if proof in proven: continue
                run([ROOT / 'build/solver/shovey-solve-classic', 'verify', '--level', level['number'], board, level['solution']])
                proven.add(proof)
            atomic(proven_path, json.dumps(sorted(proven)) + '\n')
            status('Building Shovey release', 'checking')
            run(['sh', 'tests/release_test.sh', toolchain])
            run(['python3', 'tests/assets_test.py'])
            run(['make', 'player-linux'])
            status('Checking game screens', 'checking')
            private = [
                'env', '-u', 'DISPLAY', '-u', 'WAYLAND_DISPLAY', '-u', 'XAUTHORITY', '-u', 'DBUS_SESSION_BUS_ADDRESS',
                '-u', 'SESSION_MANAGER', 'YUE_DESKTOP_RECOVERY=0', 'SDL_AUDIODRIVER=dummy',
                'xvfb-run', '-a', '-n', '400', '-s', '-screen 0 1600x1100x24']
            try:
                run([*private, 'python3', ROOT / 'tests/shovey_standalone_ui_test.py',
                     '--binary', ROOT / 'build/player/linux/shovey', '--inbe-source', inbe])
            except subprocess.CalledProcessError:
                # The screen check reads the level count from approved.json;
                # an approval during this build makes it expect the next
                # campaign, which the rebuild below checks.
                if fingerprint() == approved_hash:
                    raise
            if fingerprint() != approved_hash:
                # Requests for this snapshot join the next campaign build.
                Queue(ROOT).advance(ACTIVE_IDS, 'building', 'Campaign changed; rebuilding')
                continue
            bundle = ROOT / 'build/player/shovey.zx'
            receipt.update(phase='checked', sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                           checks=['approved routes', 'release boundary and saves', 'assets', 'Shovey UI'])
            atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
            status('Pushing release', 'publishing')
            push_release(receipt, output)
            receipt['phase'] = 'pushed'
            atomic(receipt_path, json.dumps(receipt, indent=2) + '\n')
            complete_release(config, receipt, output)
            if fingerprint() == approved_hash:
                return 0


def main(force=False):
    global ACTIVE_IDS
    if force:
        approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
        Queue(ROOT).enqueue(approved, available=len(approved))
    # The live campaign never waits for a release build.
    publish_live_now()
    # Requests are durable before a worker starts. Waiting workers take the
    # same lock, then see whether the previous worker already handled them.
    with (STATE / 'publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
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
