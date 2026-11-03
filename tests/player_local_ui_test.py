"""Bundled Classic opens with downloads declined; Profile survives navigation."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
parser.add_argument('--profile-only', action='store_true', help='isolate Profile when local Play is broken')
args = parser.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
root = Path(__file__).resolve().parents[1]
work = root / 'work/player-local-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=root, check=True)
work.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(args.driver_source.resolve()))
from ui_driver import UiDriver
from world_map_test_support import assert_fullscreen_map, enter_classic_map, start_map_destination

with tempfile.TemporaryDirectory(dir=work, prefix='guest-') as directory:
    profile = Path(directory)
    records = profile / 'games/arcade.shovey-player/records'
    records.mkdir(parents=True)
    (records / 'level-updates').write_text('off')
    (records / 'controls').write_text('off')
    driver = UiDriver(profile / 'driver')
    log_path = work / 'classic-profile.log'
    with log_path.open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
            env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile),
                'ENTITY_DATA': str(profile / 'entity'), 'XDG_DATA_HOME': str(profile / 'xdg'), 'LANG': 'en_US.UTF-8'},
            stdout=log, stderr=subprocess.STDOUT)
        driver.attach(child, log_path)
        try:
            driver.wait(label='Play', role='button', timeout=60)
            if not args.profile_only:
                # Play opens the world map; its Play starts the selected board.
                driver.press(label='Play', role='button')
                enter_classic_map(driver)
                start_map_destination(driver, 1)
                driver.wait(contains='Level 1 / ', role='text', timeout=30)
                if driver.find(label='Got it', role='button'):
                    driver.press(label='Got it', role='button')
                assert not driver.find(contains='Request rejected')
                assert not driver.find(contains='Download')
                # Escape returns from the level to the map, then to the title.
                driver.key('escape')
                assert_fullscreen_map(driver)
                assert not driver.find(contains='Level 1 / ', visible=True), 'Escape left the level on screen'
                driver.key('escape')
                driver.wait(label='Play', role='button')
            driver.press(key=49204, role='button')
            driver.wait(label='Sign in', timeout=30)
            driver.wait_idle(frames=8)
            assert child.poll() is None, 'Profile terminated the player'
            driver.key('escape')
            driver.wait(label='Play', role='button')
            assert child.poll() is None
            assert (records / 'level-updates').read_text() == 'off'
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
print('Player Profile local UI test passed' if args.profile_only else
      'Player local UI tests: bundled Classic map and level with downloads off, Escape to map and title, Profile passed')
