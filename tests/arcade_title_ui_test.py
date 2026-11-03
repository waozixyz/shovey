"""Verify Arcade console/shortcut -> artwork title -> Play -> map and download consent.

Build Arcade's collection and native player through build-queue first. This test
starts its own private display and serves only that build's local packages.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/arcade-library'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--arcade-source', type=Path, default=ROOT.parent / 'arcade')
parser.add_argument('--driver-source', type=Path, default=ROOT.parents[1] / 'apps/breeze')
parser.add_argument('--ui', action='store_true', help=argparse.SUPPRESS)
parser.add_argument('--title-only', action='store_true', help='Focus on title, Play, Home and HUD; the full test also exercises Editor')
args = parser.parse_args()
subprocess.run(['git', 'check-ignore', '-q', str(WORK)], cwd=ROOT, check=True)
WORK.mkdir(parents=True, exist_ok=True)
if not args.ui:
    environment = {key: value for key, value in os.environ.items() if key not in
                   ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
                    'SESSION_MANAGER', 'GDK_DISPLAY')}
    environment.update(YUE_DESKTOP_RECOVERY='0', SDL_AUDIODRIVER='dummy', TMPDIR=str(WORK))
    subprocess.run(['xvfb-run', '-a', '-n', '400', '-s', '-screen 0 1800x1400x24',
                    sys.executable, __file__, '--ui', '--arcade-source', str(args.arcade_source.resolve()),
                    '--driver-source', str(args.driver_source.resolve()),
                    *(['--title-only'] if args.title_only else [])],
                   cwd=ROOT, env=environment, check=True)
    sys.exit(0)
root = args.arcade_source.resolve()
out = WORK
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
sys.path.insert(0, str(root / 'tests'))
sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
sys.path.insert(0, str(ROOT / 'tests'))
from collection_ui_test import package_server, answer_library_question
from world_map_test_support import private_environment, digest
from ui_driver import UiDriver
from arcade_entry_test import assert_real_title, exercise_title

# The probe requires a collection built with the reviewed controller.
metadata = json.loads((root / 'build/arcade.json').read_text())
assert metadata['apps_sha256'] == (root / 'apps-controller.sha256').read_text().strip(), \
    'Rebuild Arcade with its reviewed Apps controller before this test'
assert digest(root / 'build/arcade.zx') == metadata['sha256']
results = []
(out / 'arcade-route-results.json').write_text('[]\n')
for shortcut in (False, True):
    with package_server(root) as (origin, server), tempfile.TemporaryDirectory(prefix='arcade-route-', dir=out) as folder:
        profile = Path(folder)
        records = profile / 'games/inbe.arcade/records'
        records.mkdir(parents=True)
        driver = UiDriver(profile / 'driver')
        log_path = out / ('arcade-shortcut.log' if shortcut else 'arcade-console.log')
        with log_path.open('w') as log:
            child = subprocess.Popen([str(root / 'build/arcade'), *(['--app', 'shovey'] if shortcut else [])],
                cwd=root, env=private_environment(profile, driver.environment()) | {'ARCADE_PACKAGE_ORIGIN': origin},
                stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                answer_library_question(driver)
                metadata = json.loads((root / 'build/arcade.json').read_text())
                game = next(row for row in metadata['children'] if row['id'] == 'arcade.shovey')

                def activate_shovey():
                    covers = [n for n in driver.find(label='Shovey', role='button', visible=True) if n['height'] > 100]
                    assert covers, 'Shovey cover missing'
                    driver.press(key=covers[0]['key'], role='button')

                if shortcut:
                    driver.wait(label='Download', role='button', visible=True)
                    assert game['sha256'] not in server['requests'], 'Shortcut downloaded without consent'
                    driver.press(label='Download', role='button')
                    assert_real_title(driver)
                else:
                    assert game['sha256'] not in server['requests'], 'Browsing downloaded the game'
                    activate_shovey()  # Centred cover activation grants its download.
                    deadline = time.monotonic() + 120
                    payload = profile / 'resources/downloads' / (game['sha256'] + '.zx')
                    while not payload.exists() or driver.find(contains='Downloading', visible=True):
                        assert time.monotonic() < deadline, 'Shovey did not finish its cover download'
                        driver.wait_idle(frames=3)
                    driver.wait_idle(frames=30)
                    assert not driver.find(key=49208, visible=True), 'Download completion opened a game without a fresh activation'
                    activate_shovey()
                payload = profile / 'resources/downloads' / (game['sha256'] + '.zx')
                assert digest(payload) == game['sha256']
                assert_real_title(driver)
                for width, height in ((1440, 900), (720, 1080)):
                    exercise_title(driver, width, height)
                assert driver.find(label='Shovey', role='image', visible=True), 'Proper title artwork missing'
                assert not driver.find(key=20105, visible=True), 'Arcade bypassed artwork title'
                assert not driver.find(key=20510, visible=True), 'Removed Play/Editor title returned'
                windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
                assert len(windows) == 1
                window = windows[0]
                assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                subprocess.run(['import', '-window', window, str(out / ('arcade-shortcut-title.png' if shortcut else 'arcade-console-title.png'))], check=True)
                driver.press(label='Play', role='button')
                driver.wait(key=20105, visible=True, timeout=120)
                assert not driver.find(key=20510, visible=True), 'Second title after Play'
                # The collection Home route returns to the shelf. Opening an
                # installed game still shows exactly its artwork title once.
                driver.key(290)
                driver.wait(key=50400, visible=True, timeout=30)
                driver.wait(label='Profile', role='button', visible=True)
                driver.wait(label='Dew', role='button', visible=True)
                activate_shovey()
                driver.wait(label='Play', role='button')
                assert not driver.find(key=20105, visible=True)
                assert not driver.find(key=20510, visible=True)
                assert not driver.find(label='Download', role='button', visible=True)
                if not args.title_only:
                    # The editor remains a normal in-game cover and keeps shared
                    # Apps installation/return handling.
                    driver.press(label='Next', role='button')
                    driver.wait_idle(frames=20)
                    driver.press(label='Open', role='button')
                    deadline = time.monotonic() + 120
                    while not driver.find(label='Levels', role='button', visible=True):
                        assert time.monotonic() < deadline, 'In-game Editor did not open'
                        if driver.find(label='Shovey Editor', visible=True):
                            for label in ('Download', 'Install', 'Open'):
                                if driver.find(label=label, role='button', visible=True):
                                    driver.press(label=label, role='button')
                                    break
                        driver.wait_idle(frames=3)
                    driver.key('escape')
                    driver.wait(label='Open', role='button')
                    driver.press(label='Previous', role='button')
                    driver.wait_idle(frames=20)
                    assert_real_title(driver)
                driver.press(label='Play', role='button')
                driver.wait(key=20105, visible=True)
                results.append({'route': 'Arcade --app shovey' if shortcut else 'Arcade console',
                                'download_consent': True, 'title_then_map': True, 'in_game_editor': not args.title_only,
                                'orientations': ['landscape', 'portrait'], 'swipe_and_chest': True})
                (out / 'arcade-route-results.json').write_text(json.dumps(results, indent=2) + '\n')
            except BaseException:
                try:
                    (out / 'arcade-route-failure.json').write_text(json.dumps(driver.tree(), indent=2) + '\n')
                    (out / 'arcade-route-failure-context.json').write_text(json.dumps(
                        {'shortcut': shortcut, 'requests': server['requests']}, indent=2) + '\n')
                except BaseException:
                    pass
                raise
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)
(out / 'arcade-route-results.json').write_text(json.dumps(results, indent=2) + '\n')
print('Arcade console and shortcut: cover download -> proper artwork title -> Play -> map passed')
