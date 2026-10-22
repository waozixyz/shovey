"""Upgrade a running signed Arcade through Inbe's ordinary update action."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--inbe-source', type=Path, required=True)
    parser.add_argument('--previous-metadata', type=Path, required=True)
    parser.add_argument('--previous-bundle', type=Path, required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--expected-levels', type=int, required=True)
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
    output = Path(__file__).resolve().parents[1] / 'build/inbe-update-ui-test'
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.inbe_source / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')

    @contextlib.contextmanager
    def application(profile, name):
        with (output / (name + '.log')).open('w') as log:
            environment = os.environ | driver.environment() | {'APP_DATA_ROOT': str(profile)}
            environment.pop('INBE_NODE_APP_FILE', None)
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.inbe_source,
                                     env=environment, stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, output / (name + '.log'))
            try:
                driver.tree()
                yield
            finally:
                child.terminate()
                child.wait(timeout=10)

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
        profile = Path(temporary)
        with application(profile, 'bootstrap'):
            pass
        release = json.loads(args.previous_metadata.read_text())
        artifact = release['artifacts'][0]
        assert release['app_id'] == 'inbe.arcade'
        assert hashlib.sha256(args.previous_bundle.read_bytes()).hexdigest() == artifact['sha256']
        cache = profile / 'packages'
        cache.mkdir(exist_ok=True)
        shutil.copyfile(args.previous_bundle, cache / f'arcade.{artifact["sha256"]}.zib')
        shutil.copyfile(args.previous_metadata, cache / 'arcade.current.json')
        with sqlite3.connect(profile / 'inbe.db') as db:
            user = db.execute("SELECT id FROM users WHERE kind='local' LIMIT 1").fetchone()[0]
            settings = dict(language='en', language_system=0, language_setup_done=1,
                            apps_setup_done=1, tutorial_seen=1, habits_guide_seen=1,
                            launcher_guide_seen=1, lumi_guides_seen=127,
                            app_used_practices=1, package_updates_allowed=0,
                            apps_last_update_check=1900000000,
                            node_apps_checked_at=int(time.time()), navigation_placement=2,
                            node_apps_offers='arcade|Arcade\n', node_app_slot_0='arcade',
                            app_used_arcade=1)
            for key, value in settings.items():
                db.execute('INSERT INTO settings(user_id,key,value,updated_at) VALUES(?,?,?,1) '
                           'ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value',
                           (user, key, str(value)))
        with application(profile, 'upgrade'):
            driver.press(label='Apps', role='button')
            driver.press(label='Find an app', role='text_field')
            driver.type('Arcade')
            driver.press(label='Arcade', role='button')
            driver.press(label='Shovey', role='button')
            driver.press(label='Shovey Classic', role='button')
            driver.wait(label='Restart', role='button')
            heading = next(node['label'] for node in driver.tree() if node['label'].startswith('Level 1 / '))
            assert int(heading.rsplit(' / ', 1)[1]) > args.expected_levels, 'The fixture must start with the old campaign'
            driver.key('left')
            # The collection stays loaded after returning to the launcher.
            for attempt in range(8):
                if driver.find(label='Apps', role='button', visible=True):
                    break
                back = driver.find(label='Back', role='button', visible=True)
                assert back
                driver.press(key=min(back, key=lambda node: node['y'])['key'])
            driver.press(label='Apps', role='button')
            driver.press(label='Find an app', role='text_field')
            driver.key('a', control=True)
            driver.type('Arcade')
            driver.wait_idle(frames=3)
            deadline = time.monotonic() + 45
            while True:
                driver.press(label='App options', role='button')
                if driver.find(label='Update', visible=True):
                    break
                driver.key('escape')
                assert time.monotonic() < deadline, 'The fresh game-open update check did not find the release'
                time.sleep(.2)
            driver.press(label='Update', role='selectable')
            driver.press(label='Update', role='button')
            deadline = time.monotonic() + 90
            while json.loads((cache / 'arcade.current.json').read_text())['version'] != args.expected_version:
                assert time.monotonic() < deadline, driver.text()
                driver.tree()
                time.sleep(.1)
            driver.wait_idle(frames=12)
            driver.press(label='Arcade', role='button')
            driver.press(label='Shovey', role='button')
            driver.press(label='Shovey Classic', role='button')
            driver.wait(label=f'Level 1 / {args.expected_levels}')
            assert len(driver.find(label='Back', role='button', visible=True)) >= 2
            driver.press(label='Levels', role='button')
            assert not driver.find(label=str(args.expected_levels + 1), role='button'), 'Unapproved levels leaked into the update'
            driver.press(label='Continue', role='button')
            driver.wait(label=f'Level 1 / {args.expected_levels}')
    print('Inbe: the ordinary signed update replaces a running old Arcade campaign without restarting the host')


if __name__ == '__main__':
    main()
