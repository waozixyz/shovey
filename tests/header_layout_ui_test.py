"""Exercise the production cover header and shop routes on a private display."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
    root = Path(__file__).resolve().parents[1]
    output = root / 'work/header-layout-ui-test'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve()))
    from ui_driver import UiDriver

    def separated(a, b):
        return (a['x'] + a['width'] <= b['x'] or b['x'] + b['width'] <= a['x'] or
                a['y'] + a['height'] <= b['y'] or b['y'] + b['height'] <= a['y'])

    def without_game_shortcuts():
        for key in (61000, 61001, 61002, 61003):
            assert not driver.find(key=key), f'In-game shortcut leaked: {key}'

    for width, height in ((320, 640), (900, 640)):
        with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as folder:
            profile = Path(folder)
            records = profile / 'games/arcade.shovey/records'
            records.mkdir(parents=True)
            today = int(time.time()) // 86400
            # A real valid guest record, separate from every owner account.
            plan = struct.pack('<BHIB', 1, 1, today - 1, 1) + struct.pack('<I', 20)
            (records / 'earned.shovey.daily-chest.guest.v1').write_text('c1:' + plan.hex())
            (records / 'shop.v1.guest').write_text(json.dumps(
                dict(version=1, owner='', selected=0, owned=0, spent=0)))
            (profile / 'games/arcade.shovey-player/records').mkdir(parents=True)
            (profile / 'games/arcade.shovey-player/records/level-updates').write_text('off')
            driver = UiDriver(profile / 'driver')
            log_path = output / f'{width}.log'
            with log_path.open('w') as log:
                child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                    env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile), 'LANG': 'en_US.UTF-8'},
                    stdout=log, stderr=subprocess.STDOUT)
                driver.attach(child, log_path)
                try:
                    driver.wait(label='Play', role='button', timeout=60)
                    if driver.find(label='Download new levels when they come out?', role='text'):
                        driver.press(label='Not now', role='button')
                    windows = subprocess.check_output(
                        ['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
                    assert len(windows) == 1
                    window = windows[0]
                    assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                    subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
                    deadline = time.monotonic() + 10
                    while driver.tree()[0]['width'] != width:
                        assert time.monotonic() < deadline, 'Window did not resize'
                        time.sleep(.05)
                    market = driver.wait(key=49200, role='button')
                    chest = driver.wait(key=49202, role='button')
                    assert chest['x'] == market['x'] and chest['y'] >= market['y'] + market['height']
                    coins = driver.wait(key=49211, role='text', label='20')
                    dew = driver.wait(key=49213, role='text')
                    assert coins['x'] > market['x'] + market['width'] and dew['x'] == coins['x']
                    assert dew['y'] > coins['y']
                    for button in (driver.wait(key=49204), driver.wait(key=49206)):
                        assert separated(coins, button) and separated(dew, button)
                    logos = [node for node in driver.tree() if node['kind'] == 'image' and
                             119 <= node['y'] <= 121 and node['width'] <= 361]
                    assert logos, 'Compact cover logo is missing'
                    for logo in logos:
                        assert separated(logo, market) and separated(logo, chest)
                        assert logo['width'] <= (width * .58 + 1 if width < 600 else 361)
                    subprocess.run(['import', '-window', window, str(output / f'{width}.png')], check=True)
                    driver.press(label='Play', role='button')
                    driver.wait(label='How do you want to move?', role='text')
                    without_game_shortcuts()
                    driver.press(label='Swipe and tap', role='button')
                    driver.wait_gone(label='How do you want to move?', role='text')
                    if driver.find(label='Got it', role='button'):
                        driver.press(label='Got it', role='button')
                        driver.wait_gone(label='Got it', role='button')
                    driver.wait(label='Levels', role='button')
                    without_game_shortcuts()
                    driver.press(label='Levels', role='button')
                    driver.wait(label='Continue', role='button')
                    without_game_shortcuts()
                    driver.press(label='Back', role='button')
                    driver.wait(label='Levels', role='button')
                    driver.press(label='Back', role='button')
                    driver.wait(key=49200, role='button')
                    driver.press(label='Next', role='button')
                    driver.wait(label='Open', role='button')
                    driver.wait_idle(frames=3, timeout=5)
                    editor_logos = [node for node in driver.tree() if node['kind'] == 'image' and
                                    119 <= node['y'] <= 121 and node['width'] <= 361]
                    assert editor_logos and any('Editor' in node['label'] for node in editor_logos)
                    assert not driver.find(label='Editor', role='text'), 'Redundant caption returned'
                    subprocess.run(['import', '-window', window, str(output / f'{width}-editor.png')], check=True)
                    driver.press(label='Previous', role='button')
                    driver.wait(label='Play', role='button')
                    for key in (49200, 49202):
                        driver.press(key=key, role='button')
                        driver.wait(key=61101, role='button', timeout=60)
                        if key == 49202:
                            driver.press(key=63002, role='button')
                        driver.press(key=61101, role='button')
                        driver.wait(key=49200, role='button')
                        driver.wait(key=49211, role='text', label='45' if key == 49202 else '20')
                    driver.press(key=49204, role='button')
                    driver.key('escape')
                    driver.wait(key=49200, role='button')
                    assert child.poll() is None
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)
    print('Header local UI test passed: 320/900px layouts, compact clear titles, stored guest coins, Dew readout, title-only Market/Chest, Back routing and Profile navigation')


if __name__ == '__main__':
    main()
