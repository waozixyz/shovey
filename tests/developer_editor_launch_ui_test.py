"""The desktop launcher uses the binary's folder; artwork and drafts use the project.

Run on a private Xvfb display. Only disposable data and a copied executable
live in the fixture; no owner drafts or desktop windows are touched.
"""
import os
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/developer-editor-launch-test'
profile = output / 'profile'
binary_folder = profile / 'build/private-editor'
binary_folder.mkdir(parents=True, exist_ok=True)
(profile / 'levels').mkdir(exist_ok=True)
(profile / 'backup/editor-drafts').mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / 'levels/classic.json', profile / 'levels/classic.json')
for folder in ('assets/shovey/sprites', 'assets/shovey-landscape/sprites'):
    shutil.copytree(ROOT / folder, profile / folder, dirs_exist_ok=True)
binary = binary_folder / 'shovey-level-editor'
shutil.copy2(ROOT / 'build/private-editor/shovey-level-editor', binary)
(profile / 'backup/editor-drafts/orientation').write_text('landscape')
environment = {key: value for key, value in os.environ.items()
               if key not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS',
                              'SESSION_MANAGER', 'GDK_DISPLAY')}
environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
label = os.environ.get('EDITOR_LAUNCH_LABEL', 'current')


def capture(name, cwd):
    marker = profile / 'backup/editor-drafts/place'
    marker.write_text('65')  # argv must select 63 in this profile, from either cwd.
    (binary_folder / 'backup/editor-drafts/place').unlink(missing_ok=True)
    with (output / f'{label}-{name}.log').open('w') as log:
        child = subprocess.Popen([str(binary), '63'], cwd=cwd, env=environment,
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            window = None
            for attempt in range(150):
                found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid',
                                        str(child.pid)], capture_output=True, text=True)
                if found.stdout.split():
                    window = found.stdout.split()[0]
                    break
                assert child.poll() is None, 'Editor exited before its private window opened'
                time.sleep(.05)
            assert window, 'No private editor window'
            time.sleep(.6)
            screenshot = output / f'{label}-{name}.png'
            subprocess.run(['import', '-window', window, str(screenshot)], check=True)
            assert marker.read_text().strip() == '63', 'Startup selected a different draft folder'
            assert not (binary_folder / 'backup/editor-drafts/place').exists(), 'Drafts went into the build folder'
            subprocess.run(['xdotool', 'windowfocus', window], check=True)
            for unused_round in range(2):
                for number in (*range(64, 69), *range(67, 62, -1)):
                    key = 'n' if number > int(marker.read_text()) else 'p'
                    subprocess.run(['xdotool', 'key', '--window', window, key], check=True)
                    deadline = time.monotonic() + 3
                    while marker.read_text().strip() != str(number) and time.monotonic() < deadline:
                        assert child.poll() is None, 'Editor exited during navigation'
                        time.sleep(.025)
                    assert marker.read_text().strip() == str(number), 'Navigation changed the wrong draft folder'
            time.sleep(.2)
            revisited = output / f'{label}-{name}-after-navigation.png'
            subprocess.run(['import', '-window', window, str(revisited)], check=True)
            with Image.open(screenshot).convert('RGB') as first, Image.open(revisited).convert('RGB') as again:
                bounds = (8, 110, first.width - 376, first.height - 8)
                assert ImageChops.difference(first.crop(bounds), again.crop(bounds)).getbbox() is None, \
                    'Repeated navigation corrupted or lost cached artwork'
            return screenshot
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


project = capture('project', profile)
launched = capture('binary-folder', binary_folder)
with Image.open(project).convert('RGB') as expected, Image.open(launched).convert('RGB') as actual:
    assert actual.size == expected.size
    # Compare the full editing area, including the actual sprite pixels.
    bounds = (8, 110, actual.width - 376, actual.height - 8)
    assert ImageChops.difference(expected.crop(bounds), actual.crop(bounds)).getbbox() is None, \
        'Launching from the build folder changed or lost the board artwork'
print('Classic editor: build-folder and project launches use the same artwork, level and draft folder; '
      'repeated navigation through 63–68 preserves the rendered images')
