"""Verify Shovey navigation in dock-based and immersive Inbe game hosts."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageChops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--inbe-source', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True,
                        help='Arcade collection built with these Shovey sources')
    parser.add_argument('--release-metadata', type=Path,
                        help='Load the signed installed package cache instead of a developer override')
    parser.add_argument('--host-navigation-only', action='store_true',
                        help='Check the working host Back control on older Inbe versions')
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
    root = Path(__file__).resolve().parents[1]
    approved_count = len(json.loads((root / 'levels/approved.json').read_text())['levels'])
    output = root / 'build/inbe-navigation-ui-test'
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.inbe_source / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')

    @contextlib.contextmanager
    def application(profile, name, bundle):
        log_path = output / (name + '.log')
        with log_path.open('w') as log:
            environment = os.environ | driver.environment() | {'APP_DATA_ROOT': str(profile)}
            environment.pop('INBE_NODE_APP_FILE', None)
            if not args.release_metadata:
                environment['INBE_NODE_APP_FILE'] = str(bundle)
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.inbe_source,
                                     env=environment,
                                     stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                driver.tree()
                window = subprocess.check_output(
                    ['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                    text=True, timeout=10).splitlines()[0]
                subprocess.run(['xdotool', 'windowsize', window, '390', '844'], check=True)
                driver.wait_idle(frames=3)
                yield child, window
            finally:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)

    def capture(child, window, name):
        assert int(subprocess.check_output(['xdotool', 'getwindowpid', window])) == child.pid
        path = output / (name + '.png')
        subprocess.run(['import', '-window', window, str(path)], check=True, timeout=10)
        with Image.open(path) as image:
            return image.convert('RGB')

    for edition, title in (('classic', 'Shovey Classic'), ('editor', 'Shovey Editor')):
        bundle = args.bundle.resolve()
        assert bundle.is_file(), bundle
        with tempfile.TemporaryDirectory(prefix=edition + '-', dir=output) as directory:
            profile = Path(directory)
            with application(profile, edition + '-bootstrap', bundle):
                assert (profile / 'inbe.db').is_file()
            if args.release_metadata:
                release = json.loads(args.release_metadata.read_text())
                artifact = release['artifacts'][0]
                assert release['app_id'] == 'inbe.arcade'
                assert bundle.stat().st_size == artifact['size']
                assert hashlib.sha256(bundle.read_bytes()).hexdigest() == artifact['sha256']
                cache = profile / 'packages'
                cache.mkdir(exist_ok=True)
                shutil.copyfile(bundle, cache / f'arcade.{artifact["sha256"]}.zib')
                shutil.copyfile(args.release_metadata, cache / 'arcade.current.json')
            with sqlite3.connect(profile / 'inbe.db') as db:
                user = db.execute("SELECT id FROM users WHERE kind='local' LIMIT 1").fetchone()[0]
                settings = dict(language='en', language_system=0, language_setup_done=1,
                                apps_setup_done=1, tutorial_seen=1, habits_guide_seen=1,
                                launcher_guide_seen=1, lumi_guides_seen=127,
                                app_used_practices=1, package_updates_allowed=0,
                                apps_last_update_check=1900000000,
                                node_apps_checked_at=int(time.time()), navigation_placement=2,
                                node_apps_offers='arcade|Arcade\n', node_app_slot_0='arcade',
                                app_used_arcade=1, app_used_leaderboard=1)
                for key, value in settings.items():
                    db.execute('INSERT INTO settings(user_id,key,value,updated_at) VALUES(?,?,?,1) '
                               'ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value',
                               (user, key, str(value)))
            with application(profile, edition, bundle) as (child, window):
                driver.wait(label='Apps', role='button')
                driver.wait_idle(frames=12)
                before_nodes = driver.tree()
                before = capture(child, window, edition + '-before')
                before_apps = driver.find(label='Apps', role='button', visible=True)[0]
                origin = before_nodes[0]
                before_box = (round(before_apps['x'] - origin['x']),
                              round(before_apps['y'] - origin['y']),
                              round(before_apps['x'] - origin['x'] + before_apps['width']),
                              round(before_apps['y'] - origin['y'] + before_apps['height']))
                driver.press(label='Apps', role='button')
                driver.press(label='Arcade', role='button')
                driver.wait_gone(label='Find an app', role='text_field', timeout=30)
                driver.press(label='Shovey', role='button')
                driver.press(label=title, role='button')
                if edition == 'classic':
                    driver.wait(label='Restart', role='button')
                    driver.wait(label=f'Level 1 / {approved_count}', role='text')
                    # Exercise Shovey's own action, below Inbe's return bar.
                    back = driver.find(label='Back', role='button', visible=True)
                    assert len(back) == 1 if args.host_navigation_only else len(back) >= 2, 'Missing working Back action'
                    driver.press(key=max(back, key=lambda node: node['y'])['key'])
                    driver.wait(label='Shovey Classic', role='button')
                    driver.press(label='Shovey Classic', role='button')
                    driver.press(label='Levels', role='button')
                    back = driver.find(label='Back', role='button', visible=True)
                    assert len(back) == 1 if args.host_navigation_only else len(back) >= 2, 'Missing working selector Back action'
                    driver.press(key=max(back, key=lambda node: node['y'])['key'])
                    driver.wait(label='Shovey Classic', role='button')
                    driver.press(label='Shovey Classic', role='button')
                    driver.wait(label='Restart', role='button')
                    driver.key('left')
                else:
                    driver.press(label='Island', role='button')
                    driver.wait(label='New level', role='button')
                    assert not driver.find(contains='Level 1', role='button'), 'Unpublished Island story level is visible'
                    driver.press(key=max(driver.find(label='Back', role='button', visible=True), key=lambda node: node['y'])['key'])
                    driver.press(label='Classic', role='button')
                    driver.press(label='New level', role='button')
                    driver.press(label='Play', role='button')
                    driver.wait(label='Restart', role='button')
                    driver.key('right')
                driver.wait_idle(frames=12)
                apps = driver.find(label='Apps', role='button', visible=True)
                if not apps:
                    # Current Inbe intentionally hides its navigation inside
                    # games. Back must return through the game's own pages to
                    # Arcade, where the host dock becomes usable again.
                    capture(child, window, edition + '-immersive-playing')
                    for attempt in range(8):
                        back = driver.find(label='Back', role='button', visible=True)
                        assert back, f'{edition}: immersive game has no visible Back action'
                        driver.press(key=min(back, key=lambda node: node['y'])['key'])
                        driver.wait_idle(frames=3)
                        apps = driver.find(label='Apps', role='button', visible=True)
                        if apps:
                            break
                    assert apps, f'{edition}: immersive game has no return to host navigation'
                    driver.wait(label='Arcade')
                dock = apps[0]
                after = capture(child, window, edition + '-playing')
                # Dock hosts retain the dock while playing; immersive hosts
                # restore its pixels and actions when the game returns.
                origin = driver.tree()[0]
                box = (round(dock['x'] - origin['x']), round(dock['y'] - origin['y']),
                       round(dock['x'] - origin['x'] + dock['width']),
                       round(dock['y'] - origin['y'] + dock['height']))
                (output / (edition + '-dock.json')).write_text(json.dumps({
                    'before_apps': before_apps, 'before_origin': before_nodes[0],
                    'apps': dock, 'origin': origin, 'before_box': before_box, 'box': box}, indent=2))
                assert 0 <= box[0] < box[2] <= after.width and 0 <= box[1] < box[3] <= after.height, box
                assert len(after.crop(box).getcolors(100000) or []) > 10, 'Apps dock pixels are blank'
                difference = ImageChops.difference(before.crop(before_box), after.crop(box))
                assert difference.getbbox() is None, f'{edition}: game painted over the host dock'
                driver.press(label='Apps', role='button')
                driver.wait(label='Find an app', role='text_field')
                assert driver.find(label='Arcade', role='button'), f'{edition}: dock did not open Apps'
                if edition == 'classic':
                    # Classic reports only its solved-level count, under its
                    # own identity, and Leaderboard offers Arcade by game.
                    with sqlite3.connect(profile / 'inbe.db') as db:
                        scores = db.execute("SELECT value FROM settings WHERE key='leaderboard_game_scores'").fetchone()
                    assert scores and scores[0].startswith('arcade\tarcade.shovey\tShovey Classic\tlevels\t'), scores
                    driver.press(label='Leaderboard', role='button')
                    driver.press(role='combo_box')
                    options = {node['label'] for node in driver.find(role='option', visible=True)}
                    assert options == {'Practice', 'Arcade'}, f'Leaderboard offered apps without a ranking: {options}'
                    driver.press(role='option', label='Arcade')
                    driver.wait(label='Shovey Classic', role='button')
                    driver.wait(label='Levels', role='button')
                    capture(child, window, 'leaderboard-arcade')
    print('Inbe: Classic and Editor preserve host navigation or return from immersive play; '
          'Classic reports its solved levels to an Arcade board in Leaderboard')


if __name__ == '__main__':
    main()
