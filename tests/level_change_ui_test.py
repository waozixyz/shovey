"""A level change shows its shade together with the new-levels question.

An installed Shovey opens level 1 fading in while it asks whether to download
new levels, and a won level pauses and fades into the next. Both draw over
the board in the same frames; a widget key they shared once made Kryon
refuse the frame, so Inbe went black after a win. This opens Classic in Inbe
from a fresh profile, keeps reading the screen while the question shows over
the fading level, answers it, wins level 1 with its approved route and waits
for level 2, checking that every frame finished and the app kept running.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

LEVEL_UPDATES = 'Download new levels when they come out?'
# Route letters are engine directions; in portrait they step left, up, right
# and down on the screen.
STEPS = {'0': (-1, 0), '1': (0, -1), '2': (1, 0), '3': (0, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--inbe-source', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True, help='Arcade collection built with these Shovey sources')
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
    root = Path(__file__).resolve().parents[1]
    levels = json.loads((root / 'levels/approved.json').read_text())['levels']
    output = root / 'build/level-change-ui-test'
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.inbe_source / 'tests'))
    from ui_driver import UiDriver
    from inbe_apps import open_arcade
    driver = UiDriver(output / 'driver')
    bundle = args.bundle.resolve()
    assert bundle.is_file(), bundle

    @contextlib.contextmanager
    def application(profile, name):
        log_path = output / (name + '.log')
        with log_path.open('w') as log:
            environment = os.environ | driver.environment() | {
                'APP_DATA_ROOT': str(profile), 'INBE_NODE_APP_FILE': str(bundle)}
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.inbe_source,
                                     env=environment, stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                driver.tree()
                window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                                 text=True, timeout=10).splitlines()[0]
                subprocess.run(['xdotool', 'windowsize', window, '390', '844'], check=True)
                driver.wait_idle(frames=3)
                yield child, log_path
            finally:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)

    def healthy(child, log_path, when):
        assert child.poll() is None, f'{when}: the app closed'
        text = log_path.read_text(errors='replace')
        for failure in ('Duplicate widget key', 'could not finish', 'could not open'):
            assert failure not in text, f'{when}: {failure} in {log_path}'

    with tempfile.TemporaryDirectory(prefix='level-change-', dir=output) as directory:
        profile = Path(directory)
        with application(profile, 'bootstrap'):
            assert (profile / 'inbe.db').is_file()
        with sqlite3.connect(profile / 'inbe.db') as db:
            user = db.execute("SELECT id FROM users WHERE kind='local' LIMIT 1").fetchone()[0]
            settings = dict(language='en', language_system=0, language_setup_done=1, apps_setup_done=1,
                            tutorial_seen=1, habits_guide_seen=1, launcher_guide_seen=1, lumi_guides_seen=127,
                            app_used_practices=1, package_updates_allowed=0, apps_last_update_check=1900000000,
                            node_apps_checked_at=int(time.time()), navigation_placement=2,
                            node_apps_offers='arcade|Arcade\n', node_app_slot_0='arcade', app_used_arcade=1)
            for key, value in settings.items():
                db.execute('INSERT INTO settings(user_id,key,value,updated_at) VALUES(?,?,?,1) '
                           'ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value', (user, key, str(value)))
        with application(profile, 'classic') as (child, log_path):
            driver.wait(label='Apps', role='button')
            open_arcade(driver)
            driver.wait(label='Classic', role='text', timeout=30)
            driver.press(label='Play', role='button')
            # Level 1 fades in under the question: read the screen through
            # the whole fade, which needs every frame to finish.
            driver.wait(label=LEVEL_UPDATES, role='text', timeout=30)
            for _ in range(40):
                assert driver.find(label=LEVEL_UPDATES, role='text'), 'the question went away by itself'
                time.sleep(0.05)
            healthy(child, log_path, 'question over the first level')
            driver.press(label='Not now', role='button')
            driver.wait_gone(label=LEVEL_UPDATES, role='text')
            if driver.find(label='How do you want to move?', role='text'):
                driver.press(label='Swipe and tap')
                driver.wait_gone(label='How do you want to move?', role='text')
            driver.wait(contains='Level 1 / ', role='text')
            # Win level 1 by tapping the cell next to Shovey for each step,
            # as a player does, then fade into level 2.
            def tap(dx, dy):
                me = [node for node in driver.tree() if node['label'] == 'Shovey'][0]
                x, y = me['x'] + me['width'] * (0.5 + dx), me['y'] + me['height'] * (0.5 + dy)
                for down in (False, True, False):
                    driver.pointer(x, y, down=down)
                    driver.wait_idle(frames=1, timeout=1)
                driver.release_pointer()
                driver.wait_idle(frames=2, timeout=2)
            for letter in levels[0]['solution']:
                tap(*STEPS[letter])
            driver.wait(contains='Level 2 / ', role='text', timeout=20)
            driver.wait_idle(frames=6, timeout=10)
            healthy(child, log_path, 'the fade into level 2')
    print('Level change: the first level fades in under the new-levels question and a win fades into level 2; '
          'every frame finished')


if __name__ == '__main__':
    main()
