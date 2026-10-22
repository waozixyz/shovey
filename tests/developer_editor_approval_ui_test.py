"""An approved level can publish while the editor remains usable."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/developer-editor-approval-test'
profile = output / 'profile'
drafts = profile / 'backup/editor-drafts'
for folder in (drafts, profile / 'levels', profile / 'scripts', profile / 'backup/redesign'):
    folder.mkdir(parents=True, exist_ok=True)
for path in drafts.iterdir():
    path.unlink()
if not (profile / 'assets').exists():
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
pieces = [12] * 240
pieces[13], pieces[14] = 10, 7
tiles = [kind if kind == 12 else 77 if kind == 7 else 0 for kind in pieces]
def rows(layer):
    return [''.join(f'{kind:02x}' for kind in layer[at:at + 12]) for at in range(0, 240, 12)]
level = dict(number=1, cells=rows(pieces), solution='2')
(profile / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
(profile / 'levels/classic.json').write_text(json.dumps(dict(
    edition='classic', width=12, height=20, levels=[level, dict(level, number=2)]), indent=1) + '\n')
(drafts / '001.approved').write_text(''.join(rows(pieces) + rows(tiles)) + '00' * 240)
(profile / 'scripts/editor_actions.py').write_text('''from pathlib import Path
import sys, time
root = Path('backup/editor-drafts')
(root / 'worker-started').write_text(' '.join(sys.argv[1:]))
time.sleep(2)
(root / 'worker-done').write_text('done')
''')
environment = {k: v for k, v in os.environ.items()
               if k not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
with (output / 'app.log').open('w') as log:
    child = subprocess.Popen([str(ROOT / 'build/private-editor/shovey-level-editor'), '1'],
                             cwd=profile, env=environment, stdout=log, stderr=subprocess.STDOUT)
    try:
        for attempt in range(300):
            windows = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                     capture_output=True, text=True).stdout.split()
            if windows:
                break
            assert child.poll() is None
            time.sleep(0.05)
        assert windows
        window = windows[0]
        def click(x, y):
            subprocess.run(['xdotool', 'mousemove', '--window', window, str(x), str(y), 'click', '1'], check=True)
        time.sleep(0.6)
        subprocess.run(['xdotool', 'windowfocus', window], check=True)
        click(350, 66)  # Approve also republishes an approved level.
        for attempt in range(40):
            if (drafts / 'worker-started').exists():
                break
            time.sleep(0.025)
        assert (drafts / 'worker-started').read_text() == 'update 1'
        assert not (drafts / 'worker-done').exists()
        click(480, 28)  # Next is usable before publication completes.
        time.sleep(0.15)
        assert (drafts / 'place').read_text().strip() == '2'
        assert not (drafts / 'worker-done').exists()
        subprocess.run(['import', '-window', window, str(output / 'editor.png')], check=True)
        for attempt in range(100):
            if (drafts / 'worker-done').exists():
                break
            time.sleep(0.025)
        assert (drafts / 'worker-done').exists()
        print('Approve publishes in the background; navigation remains responsive')
    finally:
        if windows:
            subprocess.run(['import', '-window', windows[0], str(output / 'last.png')], check=True)
        child.terminate()
        child.wait(timeout=10)
