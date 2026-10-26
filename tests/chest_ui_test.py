"""Revisit the actual hidden chest in a disposable save on a private display."""
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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--fixture', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
sys.path.insert(0, str(args.driver_source / 'tests'))
from ui_driver import UiDriver

output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
driver = UiDriver(output / 'driver')
keys = ('left', 'up', 'right', 'down')
route = '0300000011022333311221211122'


@contextlib.contextmanager
def application(profile, name):
    log_path = output / (name + '.log')
    with log_path.open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                                 env=os.environ | driver.environment() | {
                                     'ARCADE_DATA': str(profile), 'ENTITY_DATA': str(profile / 'entity'),
                                     'LANG': 'en_US.UTF-8', 'SDL_AUDIODRIVER': 'dummy'},
                                 stdout=log, stderr=subprocess.STDOUT)
        driver.attach(child, log_path)
        try:
            driver.wait(label='Play', role='button', timeout=60)
            driver.press(label='Play', role='button')
            driver.wait(label='Levels', role='button')
            driver.wait_gone(key=49401)
            driver.key('left')
            driver.wait(contains='29a', role='text')
            time.sleep(.7)
            for direction in route:
                driver.key(keys[int(direction)])
                time.sleep(.12)
                if driver.find(label='You found a secret chest!') or driver.find(label='Empty chest'):
                    break
            driver.wait(key=20120, timeout=10)
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)


def close():
    # The dialog has both a close icon and a Close action. Select the action.
    nodes = driver.find(label='Close', role='button')
    assert nodes
    driver.press(key=nodes[-1]['key'])
    driver.wait_gone(key=20120)


def reopen():
    driver.press(key=20126)
    driver.wait(key=20120)


def capture(child, name):
    windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
    assert len(windows) == 1
    subprocess.run(['import', '-window', windows[0], str(output / (name + '.png'))], check=True)
    (output / (name + '.json')).write_text(json.dumps(driver.tree(), indent=2) + '\n')


def check_chest_art(child, name, unclaimed):
    chest = driver.find(key=20126)[0]
    # Step back along the route so Shovey does not cover the chest's inside.
    driver.key('left')
    time.sleep(.4)
    capture(child, name)
    left, top = int(chest['x']), int(chest['y'])
    with Image.open(output / (name + '.png')) as picture:
        cell = picture.convert('RGB').crop((left, top, left + int(chest['width']), top + int(chest['height'])))
        pixels = cell.load()
        blue = sum(pixels[x, y][2] > 140 and pixels[x, y][1] > 70 and pixels[x, y][2] > pixels[x, y][0] * 1.6
                   for y in range(cell.height) for x in range(cell.width))
    assert (blue > 0) == unclaimed, f'{name}: blue Dew diamond pixels={blue}'
    driver.key('right')
    driver.wait(key=20120)


with tempfile.TemporaryDirectory(prefix='chest-', dir=output) as temporary:
    for state, expected in (('10', 'You found a secret chest!'), ('20', 'You have already claimed this chest’s Dew.')):
        profile = Path(temporary) / state
        records = profile / 'games/arcade.shovey/records'
        records.mkdir(parents=True)
        (records / 'local.campaign').write_text(args.fixture.read_text())
        (records / 'rewards').write_text('r1:' + state)
        controls = profile / 'games/arcade.shovey-player/records'
        controls.mkdir(parents=True)
        for folder in (records, controls):
            (folder / 'controls').write_text('off')
            (folder / 'level-updates').write_text('off')
        for attempt in range(2):
            with application(profile, state + '-' + str(attempt)) as child:
                driver.wait(label=expected)
                if state == '10':
                    driver.wait(label='Connect account', role='button')
                # A dialog takes movement; dismissing it leaves the player at
                # the chest, where tapping it must open the same dialog again.
                driver.key('left')
                close()
                check_chest_art(child, state + '-' + str(attempt) + '-board', state == '10')
                close()
                reopen()
                driver.wait(label=expected)
                close()
                reopen()
                driver.wait(label=expected)
                capture(child, state + '-' + str(attempt))
                assert (records / 'rewards').read_text() == 'r1:' + state
print('Chest UI local test: diamond only for unclaimed Dew, claimed chest empty; both stay open after restart and dialogs reopen')
