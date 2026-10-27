"""Exercise Pip in the real game on a private display and disposable profiles."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
parser.add_argument('--host', choices=('arcade', 'kryon'), default='arcade')
parser.add_argument('--output', type=Path, default=ROOT / 'build/friend-guide-ui-test')
args = parser.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
sys.path.insert(0, str(args.driver_source / 'tests'))
from ui_driver import UiDriver

output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
driver = UiDriver(output / 'driver')
environment = {key: value for key, value in os.environ.items()
               if key not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY')}
environment.update(SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0', LANG='en_US.UTF-8')


def wait_for(predicate, message, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError(message)


@contextlib.contextmanager
def application(profile, name):
    with (output / (name + '.log')).open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                                 env=environment | driver.environment() | {'KRYON_APP_DATA': str(profile), 'ARCADE_DATA': str(profile)},
                                 stdout=log, stderr=subprocess.STDOUT)
        driver.attach(child, output / (name + '.log'))
        try:
            driver.wait(label='Play', role='button', timeout=60)
            driver.press(label='Play', role='button')
            driver.wait(label='Levels', role='button')
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)


def resize(child, width, height):
    windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
    assert len(windows) == 1, 'Expected one window owned by the private test'
    subprocess.run(['xdotool', 'windowsize', windows[0], str(width), str(height)], check=True)
    driver.wait_idle(frames=3)
    return windows[0]


def overlap(first, second):
    return (min(first['x'] + first['width'], second['x'] + second['width']) - max(first['x'], second['x']) > 0.5 and
            min(first['y'] + first['height'], second['y'] + second['height']) - max(first['y'], second['y']) > 0.5)


def check_card(width, height, tip):
    """Pip's card fits the window, keeps clear of the bar, the status and the
    cell he points at, and its parts stay apart. Returns Pip's picture."""
    avatar = driver.find(label='Pip', role='image', visible=True)[0]
    button = driver.find(label='Got it', role='button', visible=True)[0]
    bubble = driver.find(key=20600)[0]
    focus = driver.find(key=20605)
    for node in (avatar, tip, button, bubble):
        assert node['x'] >= 0 and node['y'] >= 0
        assert node['x'] + node['width'] <= width + 1
        assert node['y'] + node['height'] <= height + 1
    header = driver.find(label='Levels', role='button', visible=True)[0]
    status = driver.find(key=20021)
    for node in (avatar, tip, button, bubble):
        assert node['y'] >= header['y'] + header['height'], 'Pip covered the bar'
        assert not status or not overlap(node, status[0]), 'Pip covered the status under the bar'
    assert not overlap(tip, button) and not overlap(tip, avatar), 'Pip, his tip and Got it overlap'
    assert focus, 'Pip pointed at nothing on the board'
    for node in (avatar, tip, button, bubble):
        assert not overlap(node, focus[0]), f'Pip’s card hid the cell he points at at {width}x{height}'
    assert focus[0]['index'] < bubble['index'], 'The highlight was drawn over Pip’s card'
    return avatar


def record_position(text):
    start = 1006 if text.startswith('C5') else 179
    return int(text[start + 4:start + 6], 16), int(text[start + 12:start + 20], 16)


def prepare(profile, level=1):
    records = profile / 'games/arcade.shovey/records' if args.host == 'arcade' else profile / 'shovey'
    records.mkdir(parents=True)
    (records / 'controls').write_text('off')
    (records / 'level-updates').write_text('off')
    if args.host == 'arcade':
        controls = profile / 'games/arcade.shovey-player/records'
        controls.mkdir(parents=True)
        (controls / 'controls').write_text('off')
        (controls / 'level-updates').write_text('off')
    if level > 1:
        saved = subprocess.check_output([str(ROOT / 'build/guide-test/native'), str(level)], text=True)
        (records / 'local.campaign').write_text(saved)
    return records


with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
    profile = Path(temporary)
    records = prepare(profile)
    seen = records / 'local.guide.seen'
    campaign = records / 'local.campaign'
    with application(profile, 'first-introduction') as child:
        driver.wait(label='Pip', role='image')
        driver.wait(label='Got it', role='button')
        driver.wait(contains='Hi, I’m Pip!', role='text')
        before = campaign.read_text()
        driver.key('right')
        driver.wait_idle(frames=3)
        assert campaign.read_text() == before, 'Movement happened while Pip was speaking'
        for width, height in ((390, 844), (960, 600), (320, 568)):
            window = resize(child, width, height)
            avatar = check_card(width, height, driver.find(contains='Hi, I’m Pip!', role='text', visible=True)[0])
            capture = output / f'pip-{width}x{height}.png'
            subprocess.run(['import', '-window', window, str(capture)], check=True)
            with Image.open(capture).convert('RGB') as image:
                left, top = int(avatar['x']), int(avatar['y'])
                region = image.crop((left, top, left + int(avatar['width']), top + int(avatar['height'])))
                orange = sum(r > 150 and g > 60 and b < 110 and r > g * 1.1 for r, g, b in region.getdata())
                assert orange > 150, 'Pip artwork did not render'
        driver.press(label='Got it', role='button')
        driver.wait_gone(label='Pip', role='image')
        assert seen.read_text() == 'G100000001'
        original = record_position(campaign.read_text())
        for key in ('left', 'up', 'right', 'down'):
            driver.key(key)
            time.sleep(.15)
            if record_position(campaign.read_text())[0] != original[0]:
                break
        assert record_position(campaign.read_text())[0] != original[0], 'Dismissing Pip did not restore movement'
        saved = campaign.read_text()
        driver.press(label='Help', role='button')
        driver.press(label='Pip’s tips', role='button')
        driver.wait(label='Pip', role='image')
        driver.press(label='Got it', role='button')
        driver.wait_gone(label='Pip', role='image')
        assert campaign.read_text() == saved, 'Replaying a tip changed the puzzle'
    with application(profile, 'restart-keeps-seen'):
        assert not driver.find(label='Pip', role='image'), 'An acknowledged tip repeated after restart'
    seen.unlink()
    with application(profile, 'upgrade-keeps-active-puzzle'):
        assert not driver.find(label='Pip', role='image'), 'Adding the guide interrupted an active saved puzzle'
        assert campaign.read_text() == saved

with tempfile.TemporaryDirectory(prefix='crate-profile-', dir=output) as temporary:
    profile = Path(temporary)
    records = prepare(profile, 2)
    with application(profile, 'new-mechanic') as child:
        driver.wait(label='Pip', role='image')
        driver.wait(contains='Push crates onto their marks.', role='text')
        assert not driver.find(contains='Hi, I’m Pip!', role='text'), 'Existing progress repeated the welcome'
        for width, height in ((390, 844), (960, 600)):
            resize(child, width, height)
            check_card(width, height, driver.find(contains='Push crates onto their marks.', role='text', visible=True)[0])
        driver.press(label='Got it', role='button')
        driver.wait_gone(label='Pip', role='image')
        assert int((records / 'local.guide.seen').read_text()[2:], 16) & 4

(output / 'result.json').write_text(json.dumps(dict(result='passed', portrait=True, landscape=True,
    small_screen=True, movement_paused=True, artwork_rendered=True, local_persistence=True,
    help_replay=True, active_save_preserved=True, new_mechanic_intro=True), indent=2) + '\n')
print('Pip: actual private game, portrait/landscape, artwork, paused input, local persistence, Help replay and new-mechanic tips passed')
