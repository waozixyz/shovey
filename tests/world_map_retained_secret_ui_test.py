"""Device-local discovery remains reachable after ordinary progress resets."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from world_map_test_support import private_environment, digest
from shovey_standalone_ui_test import answer_cover_question, answer_level_updates

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
manifest = json.loads((ROOT / 'assets/shovey/world-map/riverfold.json').read_text())
secret = next(s for s in manifest['secrets'] if s['id'] == '175b')
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
            driver.press(label='Play', role='button')
            answer_level_updates(driver)
            if driver.find(label='How do you want to move?', role='text'):
                driver.press(label='Swipe and tap')
            if driver.find(label='Got it', role='button'):
                driver.press(label='Got it')
            driver.wait(label='Levels', role='button')
            driver.press(label='Levels', role='button')
            driver.key('home')
            first = driver.wait(key=33001, role='button')
            scale = min(width - 32, 390) / 390
            dx = (secret['node']['x'] - manifest['nodes'][0]['x']) * scale
            for _ in range(round(dx / int(min(width - 32, 390) / 2))):
                driver.key('d')
            for _ in range(math.ceil(manifest['worldHeight'] / 300)):
                driver.key('page_up')
            room = driver.wait(key=34002, role='button', visible=True)
            assert room['enabled'] and room['label'] == '175b'
            nodes = driver.tree()
            assert not any(33005 <= n.get('key', 0) <= 33175 for n in nodes)
            assert not any(n.get('key') in (34001, 34003) for n in nodes)
            subprocess.run(['import', '-window', window, str(output / f'retained-{width}.png')], check=True)
            driver.press(key=34002, role='button')
            driver.wait(contains='Level 175b', role='text')
        finally:
            child.terminate()
            child.wait(timeout=10)
(output / 'result.json').write_text(json.dumps({'frontier': 1, 'retained_secret': '175b', 'ordinary_last': 4,
    'viewports': [[390, 844], [960, 600]], 'binary_sha256': digest(args.binary),
    'view_source_sha256': digest(ROOT / 'src/world_map_view.zi')}, indent=2) + '\n')
print('Retained discovery local UI test passed: frontier1, known175b reachable/opened, ordinary5+ and undiscovered siblings absent, both sizes')
