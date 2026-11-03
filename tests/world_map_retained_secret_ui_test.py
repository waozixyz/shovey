"""Device-local discovery remains reachable after ordinary progress resets."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from world_map_test_support import assert_fullscreen_map, private_environment, digest
from shovey_standalone_ui_test import answer_cover_question

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.driver_source / 'tests'))
from ui_driver import UiDriver
output = ROOT / 'work/world-map-retained-secret-test'
subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT, check=True)
output.mkdir(parents=True, exist_ok=True)
for width, height in ((390, 844), (960, 600)):
    profile = output / f'profile-{width}'
    records = profile / 'games/arcade.shovey/records'
    records.mkdir(parents=True, exist_ok=True)
    (records / 'local.campaign').unlink(missing_ok=True)
    (records / 'local.secret175b').write_text('1')
    driver = UiDriver(profile / 'driver')
    with (output / f'app-{width}.log').open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
            env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
        driver.attach(child, output / f'app-{width}.log')
        try:
            answer_cover_question(driver)
            window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0]
            assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
            subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
            # Play opens the world map directly.
            driver.press(label='Play', role='button')
            assert_fullscreen_map(driver)
            driver.key('home')
            driver.wait(key=33001, role='button')
            # The v5 map has no free camera: the wheel follows the painted road.
            window_room = None
            # Aim at the player's own window wherever the display placed it.
            for _ in range(480):
                window_room = driver.find(key=34002, role='button', visible=True)
                if window_room: break
                subprocess.run(['xdotool', 'mousemove', '--window', window, str(width // 2), str(height // 2), 'click', '4'], check=True)
                driver.wait_idle(frames=2)
            assert window_room, f'Retained discovery 159-S2 is not reachable on the v5 map at frontier 1 ({width}x{height})'
            room = driver.wait(key=34002, role='button', visible=True)
            assert room['enabled'] and room['label'] == '159-S2'
            nodes = driver.tree()
            # The whole map draws at any progress; ordinary levels past the frontier stay locked.
            assert not any(33005 <= n.get('key', 0) <= 33175 and n.get('enabled') for n in nodes), 'A future level became playable'
            assert not any(n.get('key') in (34001, 34003) for n in nodes)
            subprocess.run(['import', '-window', window, str(output / f'retained-{width}.png')], check=True)
            driver.press(key=34002, role='button')
            driver.wait(contains='Level 159-S2', role='text')
        finally:
            child.terminate()
            child.wait(timeout=10)
(output / 'result.json').write_text(json.dumps({'frontier': 1, 'retained_secret': '159-S2', 'ordinary_last': 4,
    'viewports': [[390, 844], [960, 600]], 'binary_sha256': digest(args.binary),
    'view_source_sha256': digest(ROOT / 'src/world_map_view.zi')}, indent=2) + '\n')
print('Retained discovery local UI test passed: frontier1, known 159-S2 reachable/opened, ordinary5+ locked and undiscovered siblings absent, both sizes')
