"""An approved level can publish while the editor remains usable."""
import json
import os
from pathlib import Path
import subprocess
import time
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/developer-editor-approval-test'
profile = output / 'profile'
drafts = profile / 'backup/editor-drafts'
for folder in (drafts, profile / 'levels', profile / 'scripts', profile / 'backup/redesign'):
    folder.mkdir(parents=True, exist_ok=True)
for path in drafts.iterdir():
    path.unlink()
(drafts / 'orientation').write_text('portrait')
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
campaign = dict(levels=[dict(level, number=n, tiles=rows(tiles), decorations=rows([0] * 240))
                       for n in range(1, 23)])
(profile / 'levels/approved.json').write_text(json.dumps(campaign))
(drafts / 'publish-status').write_text('Published')
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
        click(100, 28)
        time.sleep(0.2)
        def map_colors():
            subprocess.run(['xdotool', 'mousemove', '--window', window, '4', '4'], check=True)
            shot = output / 'approvals-map.png'
            subprocess.run(['import', '-window', window, str(shot)], check=True)
            with Image.open(shot).convert('RGB') as image:
                width, height = image.size
                cell_width = (width - 16 - 4 * 14) / 15
                cell_height = (height - 96 - 28 - 4 * 11) / 12
                return [image.getpixel((int(14 + (n - 1) % 15 * (cell_width + 4)),
                                        int(122 + (n - 1) // 15 * (cell_height + 4))))
                        for n in range(1, 25)]
        purple = (159, 111, 209)
        colors = map_colors()
        assert all(color == purple for color in colors[:22]), colors
        assert colors[22] != purple and colors[23] != purple
        campaign['levels'].append(dict(level, number=23, tiles=rows(tiles), decorations=rows([0] * 240)))
        (profile / 'levels/approved.json').write_text(json.dumps(campaign))
        (drafts / 'publish-status').write_text('Updating…')
        time.sleep(0.7)
        colors = map_colors()
        assert all(color == purple for color in colors[:23]) and colors[23] != purple, colors
        click(100, 28)
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
        click(390, 28)  # Return to the approved board.
        time.sleep(0.15)
        click(1300, 174)  # Moss floor, before every wall brush.
        time.sleep(0.15)
        click(476, 615)  # Cosmetic edit under Shovey preserves the winning route.
        for attempt in range(120):
            if (drafts / '001.approval-request').exists():
                break
            time.sleep(0.05)
        requested = (drafts / '001.approval-request').read_text().splitlines()[0]
        assert requested[480 + 13 * 2:482 + 13 * 2] == '67'
        assert (drafts / '001.approved').read_text() == requested
        for attempt in range(40):
            if (drafts / 'worker-started').read_text() == 'approve 1':
                break
            time.sleep(0.025)
        assert (drafts / 'worker-started').read_text() == 'approve 1'
        time.sleep(2.1)  # Let our detached disposable worker finish too.
        print('Purple campaign approvals refresh through 23; background publication, navigation and automatic updates passed')
    finally:
        if windows:
            subprocess.run(['import', '-window', windows[0], str(output / 'last.png')], check=True)
        child.terminate()
        child.wait(timeout=10)
