"""Exercise the developer editor on an isolated display and disposable drafts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]

assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/developer-editor-ui-test'
output.mkdir(parents=True, exist_ok=True)
profile = output / 'profile'
(profile / 'backup/editor-drafts').mkdir(parents=True, exist_ok=True)
(profile / 'levels').mkdir(exist_ok=True)
shutil.copyfile(ROOT / 'levels/classic.json', profile / 'levels/classic.json')
if not (profile / 'assets').exists():
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
level = json.loads((ROOT / 'levels/classic.json').read_text())['levels'][0]
pieces = ''.join(level['cells'])
(profile / 'backup/editor-drafts/001.hex').write_text(pieces + '0c' + '4d' * 239 + '00' * 240)
(profile / 'backup/editor-drafts/place').write_text('1')
environment = {key: value for key, value in os.environ.items()
               if key not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
environment |= {'YUE_DESKTOP_RECOVERY': '0', 'SDL_AUDIODRIVER': 'dummy'}
with (output / 'app.log').open('w') as log:
    child = subprocess.Popen([str(ROOT / 'build/private-editor/shovey-level-editor'), '1'],
                             cwd=profile, env=environment, stdout=log, stderr=subprocess.STDOUT)
    try:
        windows = []
        for attempt in range(300):
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Shovey level editor$'], text=True, capture_output=True)
            windows = result.stdout.split()
            if windows: break
            assert child.poll() is None, 'The editor exited before mapping its window'
            time.sleep(0.05)
        assert windows, 'The test editor did not map its own window'
        window = windows[0]
        for width, height in ((1500, 1000), (1437, 937)):
            subprocess.run(['xdotool', 'windowsize', window, str(width), str(height)], check=True)
            time.sleep(0.2)
            half = (height - 120) / 2
            cell = int(min((width - 384) / 12, (half - 26) / 20))
            origin_x = int(8 + (width - 384 - cell * 12) / 2)
            origin_y = int(138 + half + (half - 26 - cell * 20) / 2)
            tiles = [dict(x=origin_x + at % 12 * cell, y=origin_y + at // 12 * cell,
                          width=cell, height=cell) for at in range(240)]
            shot = output / f'editor-{width}.png'
            subprocess.run(['import', '-window', window, str(shot)], check=True)
            with Image.open(shot).convert('RGB') as image:
                for at in range(239):
                    if at == 0 or at % 12 == 11 or pieces[at * 2:at * 2 + 4] != '0000':
                        continue
                    tile = tiles[at]
                    x = int(tile['x'] + tile['width'])
                    y = int(tile['y'] + tile['height'] / 2)
                    for dx in (-1, 0):
                        red, green, blue = image.getpixel((x + dx, y))
                        assert green > red and green > blue, ('grass seam', x + dx, y, (red, green, blue))
        def click(x, y, button=1):
            subprocess.run(['xdotool', 'mousemove', '--window', window, str(int(x)), str(int(y)),
                            'click', str(button)], check=True)
            time.sleep(0.15)

        def draft():
            return (profile / 'backup/editor-drafts/001.hex').read_text()

        at = next(at for at in range(13, 227) if pieces[at * 2:at * 2 + 2] == '00')
        x = origin_x + (at % 12 + 0.5) * cell
        y = origin_y + (at // 12 + 0.5) * cell
        palette = width - 368
        click(palette + 178, 106)  # Objects
        click(palette + 56, 274)   # Crate
        click(x, y)
        assert draft()[at * 2:at * 2 + 2] == '09'
        click(palette + 170, 274)  # Flowers are in Objects beside the crate
        click(x, y)
        saved = draft()
        assert saved[at * 2:at * 2 + 2] == '09'
        assert saved[480 + at * 2:482 + at * 2] == '4d'
        assert saved[960 + at * 2:962 + at * 2] == '39'
        click(x, y, 3)            # Objects clears both objects and flowers, preserving the tile
        cleared = draft()
        assert cleared[at * 2:at * 2 + 2] == '00'
        assert cleared[480 + at * 2:482 + at * 2] == '4d'
        assert cleared[960 + at * 2:962 + at * 2] == '00'
        subprocess.run(['xdotool', 'windowfocus', window, 'key', '--window', window, 'z'], check=True)
        time.sleep(0.15)
        assert draft() == saved, 'Undo must restore all three layers'
        click(palette + 178, 106)  # Object erasing preserves a wall tile
        click(origin_x + 0.5 * cell, origin_y + 0.5 * cell, 3)
        assert draft()[480:482] == '0c', 'Objects erased the wall tile'
        click(x, y, 3)
        cleared = draft()
        assert cleared[at * 2:at * 2 + 2] == '00'
        assert cleared[480 + at * 2:482 + at * 2] == '4d'
        assert cleared[960 + at * 2:962 + at * 2] == '00'
        # Abyss clears every overlaid object and decoration in one stroke.
        click(palette + 170, 274)
        click(x, y)
        click(palette + 58, 106)
        click(palette + 56, 562)
        click(x, y)
        cleared = draft()
        assert cleared[at * 2:at * 2 + 2] == '00'
        assert cleared[480 + at * 2:482 + at * 2] == '41'
        assert cleared[960 + at * 2:962 + at * 2] == '00'
        click(palette + 178, 106)
        # Objects has more icons than fit vertically
        subprocess.run(['xdotool', 'mousemove', '--window', window, str(palette + 50), '500'], check=True)
        time.sleep(0.15)
        before = output / 'scroll-before.png'
        after = output / 'scroll-after.png'
        subprocess.run(['import', '-window', window, str(before)], check=True)
        subprocess.run(['xdotool', 'click', '--repeat', '8', '--delay', '20', '5'], check=True)
        time.sleep(0.5)
        subprocess.run(['import', '-window', window, str(after)], check=True)
        with Image.open(before).convert('RGB') as first, Image.open(after).convert('RGB') as second:
            assert ImageChops.difference(first.crop((palette, 132, width, height)),
                                        second.crop((palette, 132, width, height))).getbbox(), 'Palette wheel did not scroll'
            assert not ImageChops.difference(first.crop((palette, 88, width, 124)),
                                            second.crop((palette, 88, width, 124))).getbbox(), 'Tabs scrolled with the palette'
        print('Developer editor: seamless tiles, layers, layer-scoped right-click, undo, wheel scrolling and fixed tabs passed')
    finally:
        child.terminate()
        child.wait(timeout=10)
