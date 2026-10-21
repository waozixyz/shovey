"""Verify the visible abyss fall and moving animals on a private display."""
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/developer-editor-nature-test'
profile = output / 'profile'
for directory in ('levels', 'backup/editor-drafts', 'backup/redesign'):
    (profile / directory).mkdir(parents=True, exist_ok=True)
if not (profile / 'assets').exists():
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
for record in (profile / 'backup/editor-drafts').iterdir():
    record.unlink()
pieces = [0] * 240
tiles = [0] * 240
deco = [0] * 240
for at in range(240):
    if at < 12 or at >= 228 or at % 12 in (0, 11):
        tiles[at] = 12
pieces[13], tiles[14], pieces[15] = 10, 65, 7
pieces[26], pieces[45], deco[38] = 82, 83, 84
def rows(layer):
    return [''.join(f'{kind:02x}' for kind in layer[at:at + 12]) for at in range(0, 240, 12)]
level = {'number': 1, 'cells': rows(pieces), 'tiles': rows(tiles), 'decorations': rows(deco)}
(profile / 'levels/classic.json').write_text(json.dumps(
    {'edition': 'classic', 'width': 12, 'height': 20,
     'levels': [level, dict(level, number=2)]}, indent=1) + '\n')
(profile / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
environment = {k: v for k, v in os.environ.items()
               if k not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
with (output / 'app.log').open('w') as log:
    child = subprocess.Popen([str(ROOT / 'build/private-editor/shovey-level-editor'), '1'],
                             cwd=profile, env=environment, stdout=log, stderr=subprocess.STDOUT)
    try:
        window = None
        for attempt in range(600):
            found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Shovey level editor$'],
                                   text=True, capture_output=True).stdout.split()
            if found:
                window = found[0]
                break
            assert child.poll() is None, 'Editor exited'
            time.sleep(0.05)
        assert window, 'Editor did not map'
        subprocess.run(['xdotool', 'windowfocus', window, 'key', '--window', window, 'Tab'], check=True)
        time.sleep(0.15)
        subprocess.run(['xdotool', 'key', '--window', window, 'Right'], check=True)
        started = time.monotonic()
        counts = []
        # The editor uses a 20-pixel cell in its default 1500x1000 window.
        x, y, cell = 446, 585, 20
        for index, deadline in enumerate((0.02, 0.22, 0.46, 0.92)):
            time.sleep(max(0, started + deadline - time.monotonic()))
            assert child.poll() is None, f'Editor exited during the fall ({child.returncode})'
            path = output / f'fall-{index}.png'
            subprocess.run(['import', '-window', window, str(path)], check=True, timeout=5)
            with Image.open(path).convert('RGB') as shot:
                pixels = np.asarray(shot.crop((x + 2 * cell, y + cell, x + 3 * cell, y + 2 * cell))).astype(int)
            counts.append(int(((pixels[..., 1] > pixels[..., 0] * 1.3) &
                               (pixels[..., 1] > pixels[..., 2] * 1.15) & (pixels[..., 1] > 50)).sum()))
        assert counts[0] > counts[1] > counts[2] >= counts[3] == 0, ('Fall did not shrink away', counts)
        def dog_center(name):
            path = output / name
            subprocess.run(['import', '-window', window, str(path)], check=True, timeout=5)
            with Image.open(path).convert('RGB') as shot:
                pixels = np.asarray(shot.crop((x, y + 2 * cell, x + 12 * cell, y + 3 * cell))).astype(int)
            dog = (pixels[..., 0] > pixels[..., 1] * 1.15) & (pixels[..., 1] > pixels[..., 2] * 1.2) & (pixels[..., 0] > 100)
            yy, xx = np.nonzero(dog)
            assert len(xx) > 8, 'Dog is not clearly visible'
            return float(xx.mean())
        # Restart to let the animals move again after the completed fall.
        subprocess.run(['xdotool', 'key', '--window', window, 'r'], check=True)
        time.sleep(0.2)
        before = dog_center('animals-before.png')
        time.sleep(1.1)
        after = dog_center('animals-after.png')
        assert abs(after - before) > cell / 2, ('Animal did not move to another tile', before, after)
        print(f'Nature UI: abyss spiral shrank away ({counts}); visible dog moved between tiles')
    finally:
        child.terminate()
        child.wait(timeout=10)
