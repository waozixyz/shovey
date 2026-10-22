"""Check the public authoring archive, independently of the developer workspace."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
archive = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'build/admin-editor/shovey-level-editor-linux-x86_64.tar.gz').resolve()
output = ROOT / 'build/admin-editor-test'
extract = output / 'extracted'
if extract.exists():
    shutil.rmtree(extract)
extract.mkdir(parents=True)
with tarfile.open(archive) as package:
    for member in package.getmembers():
        path = Path(member.name)
        assert not path.is_absolute() and '..' not in path.parts and not member.issym() and not member.islnk()
        assert not any(word in member.name.lower() for word in ('original', '.env', 'editor-publish', 'private-editor'))
    package.extractall(extract, filter='data')
profile = extract / 'shovey-level-editor'
manifest = json.loads((profile / 'manifest.json').read_text())
for name, digest in manifest['files'].items():
    assert hashlib.sha256((profile / name).read_bytes()).hexdigest() == digest, name
story = json.loads((profile / 'levels/classic.json').read_text())
assert len(story['levels']) == 2 and story['levels'][0]['solution'] == '203'
assert not (profile / 'backup/editor-publish.json').exists()
spec = importlib.util.spec_from_file_location('packaged_actions', profile / 'scripts/editor_actions.py')
actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actions)
level = story['levels'][0]
board = actions.board_hex(level)
assert actions.verify_route(1, board, '203')
# Offline approval stores the authored board without any publisher configuration.
drafts = profile / 'backup/editor-drafts'
(drafts / '001.approval-request').write_text(board + '\n203')
(drafts / '001.approved').write_text(board)
actions.approve(1)
assert json.loads((profile / 'levels/approved.json').read_text())['levels'][0]['cells'] == level['cells']
assert (drafts / 'publish-status').read_text() == 'Approved'
assert actions.proven_variations(1, board, '203'), 'The packaged solver cannot find variations of its own starter puzzle'

assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
environment = {k: v for k, v in os.environ.items() if k not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
with (output / 'app.log').open('w') as log:
    child = subprocess.Popen([str(profile / 'run.sh')], cwd=profile, env=environment, stdout=log, stderr=subprocess.STDOUT)
    try:
        for attempt in range(300):
            windows = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], capture_output=True, text=True).stdout.split()
            if windows:
                break
            assert child.poll() is None
            time.sleep(.05)
        assert windows
        time.sleep(.4)
        subprocess.run(['import', '-window', windows[0], str(output / 'editor.png')], check=True)
        assert (drafts / 'place').read_text().strip() == '1'
    finally:
        child.terminate()
        child.wait(timeout=10)
print('Admin editor: clean archive, fresh puzzle, local approval, solver variations and native UI passed')
