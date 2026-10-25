"""The requested five redesigns load and render in the private editor.

Use disposable data and drafts on a private display; read the rendered board
back through paint/undo, then verify that revisiting it preserves the artwork.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
BINARY = Path(os.environ.get('SHOVEY_EDITOR', ROOT / 'build/private-editor/shovey-level-editor'))
OUTPUT = ROOT / 'build/editor-designs-test'
OUTPUT.mkdir(parents=True, exist_ok=True)
levels = json.loads((ROOT / 'levels/classic.json').read_text())['levels']


def wait(predicate, message):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(.025)
    raise AssertionError(message)


def normalized(level):
    values = [int(''.join(level[key])[at:at + 2], 16)
              for key in ('cells', 'tiles', 'decorations') for at in range(0, 480, 2)]
    # These five authored boards need only pit/cracked-floor placement from
    # the editor's compatible layer representation; their raw map IDs stay raw.
    for at in range(240):
        if values[at] in (4, 5, 6):
            values[at + 240], values[at] = values[at], 0
        if values[at + 240] == 71:
            values[at + 240], values[at] = 0, 71
    return ''.join(f'{kind:02x}' for kind in values)


with tempfile.TemporaryDirectory(dir=OUTPUT, prefix='profile-') as temporary:
    profile = Path(temporary)
    drafts = profile / 'backup/editor-drafts'
    drafts.mkdir(parents=True)
    (profile / 'levels').mkdir()
    shutil.copy2(ROOT / 'levels/classic.json', profile / 'levels/classic.json')
    for artwork in ('shovey', 'shovey-landscape'):
        shutil.copytree(ROOT / 'assets' / artwork / 'sprites', profile / 'assets' / artwork / 'sprites')
    (drafts / 'orientation').write_text('portrait')
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY')}
    environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
    for number in (55, 56, 64, 65, 68):
        expected = normalized(levels[number - 1])
        with (OUTPUT / f'{number}.log').open('w') as log:
            child = subprocess.Popen([str(BINARY), str(number)], cwd=profile, env=environment,
                                     stdout=log, stderr=subprocess.STDOUT)
            try:
                def window_ready():
                    assert child.poll() is None, 'Editor exited before its private window opened'
                    return subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                          capture_output=True, text=True).stdout.split()
                window = wait(window_ready, 'No private editor window')[0]
                wait(lambda: (drafts / 'place').read_text().strip() == str(number), 'Wrong level selected')
                subprocess.run(['xdotool', 'windowsize', window, '1500', '1000', 'windowfocus', window], check=True)
                time.sleep(.4)
                before = OUTPUT / f'{number}.png'
                subprocess.run(['import', '-window', window, str(before)], check=True)
                cell = 44  # floor((1000 - 118) / 20)
                x = 8 + (1500 - 384 - cell * 12) / 2 + cell / 2
                y = 110 + (1000 - 118 - cell * 20) / 2 + cell / 2
                palette = 1500 - 368
                def click(x, y):
                    subprocess.run(['xdotool', 'mousemove', '--window', window, str(int(x)), str(int(y)),
                                    'mousedown', '1'], check=True)
                    time.sleep(.08)
                    subprocess.run(['xdotool', 'mouseup', '1'], check=True)
                    time.sleep(.12)
                click(palette + 178, 106)
                click(palette + 56, 274)
                click(x, y)
                subprocess.run(['xdotool', 'key', '--window', window, 'z'], check=True)
                draft = drafts / f'{number:03}.hex'
                wait(lambda: draft.exists() and draft.read_text() == expected,
                     f'Editor did not load the verified redesigned board {number}')
                for key, target in (('n', number + 1), ('p', number)):
                    subprocess.run(['xdotool', 'key', '--window', window, key], check=True)
                    wait(lambda: (drafts / 'place').read_text().strip() == str(target), 'Wrong navigation result')
                time.sleep(.2)
                after = OUTPUT / f'{number}-revisited.png'
                subprocess.run(['import', '-window', window, str(after)], check=True)
                with Image.open(before).convert('RGB') as first, Image.open(after).convert('RGB') as second:
                    bounds = (8, 110, 1124, 992)
                    assert ImageChops.difference(first.crop(bounds), second.crop(bounds)).getbbox() is None, \
                        f'Artwork changed after revisiting redesigned level {number}'
                print(f'Private editor {number}: exact redesigned layers loaded; artwork survives navigation', flush=True)
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)
