"""Check joined abyss pixels in level 28 at fractional mobile-like scales."""
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

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--inbe-source', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
    root = Path(__file__).resolve().parents[1]
    output = root / 'build/abyss-ui-test'
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.inbe_source / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')

    @contextlib.contextmanager
    def application(profile, name):
        with (output / (name + '.log')).open('w') as log:
            environment = os.environ | driver.environment() | {
                'APP_DATA_ROOT': str(profile), 'INBE_NODE_APP_FILE': str(args.bundle.resolve())}
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.inbe_source,
                                     env=environment, stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, output / (name + '.log'))
            try:
                driver.tree()
                window = subprocess.check_output(
                    ['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                    text=True, timeout=10).splitlines()[0]
                yield child, window
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)

    def open_classic():
        driver.press(label='Apps', role='button')
        driver.press(label='Find an app', role='text_field')
        driver.type('Arcade')
        driver.press(label='Arcade', role='button')
        driver.wait_gone(label='Find an app', role='text_field', timeout=30)
        # Arcade's cover shows Shovey's Classic card; its Play opens the level.
        driver.wait(label='Classic', role='text')
        driver.wait_idle(frames=12)
        driver.press(label='Play', role='button')
        driver.wait(label='Restart', role='button', timeout=30)
        # Newer Shovey asks how to move the first time a level opens; its
        # question dims the board, so answer it before looking at pixels.
        driver.wait_idle(frames=4)
        if driver.find(label='How do you want to move?', role='text'):
            driver.press(label='Swipe and tap')
            driver.wait_gone(label='How do you want to move?', role='text')

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as directory:
        profile = Path(directory)
        with application(profile, 'bootstrap'):
            pass
        with sqlite3.connect(profile / 'inbe.db') as db:
            user = db.execute("SELECT id FROM users WHERE kind='local' LIMIT 1").fetchone()[0]
            settings = dict(language='en', language_system=0, language_setup_done=1,
                            apps_setup_done=1, tutorial_seen=1, habits_guide_seen=1,
                            launcher_guide_seen=1, lumi_guides_seen=127, app_used_practices=1,
                            package_updates_allowed=0, apps_last_update_check=1900000000,
                            node_apps_checked_at=int(time.time()), navigation_placement=2,
                            node_apps_offers='arcade|Arcade\n', node_app_slot_0='arcade',
                            app_used_arcade=1)
            for key, value in settings.items():
                db.execute('INSERT INTO settings(user_id,key,value,updated_at) VALUES(?,?,?,1) '
                           'ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value',
                           (user, key, str(value)))
        with application(profile, 'save'):
            open_classic()
            driver.press(label='Restart', role='button')
            driver.wait_idle(frames=6)
        # Unlock only this disposable profile; real player records are untouched.
        with sqlite3.connect(profile / 'inbe.db') as db:
            records = [(key, value) for key, value in db.execute(
                'SELECT key,value FROM settings WHERE user_id=?', (user,))
                if key.endswith('.campaign')]
            assert len(records) == 1, list(db.execute('SELECT key FROM settings WHERE key LIKE "%campaign%"'))
            key, value = records[0]
            assert value.startswith(('C2', 'C3', 'C4'))
            db.execute('UPDATE settings SET value=? WHERE user_id=? AND key=?',
                       (value[:2] + '1c' + value[4:], user, key))

        level = json.loads((root / 'levels/approved.json').read_text())['levels'][27]
        abyss = [int(''.join(level['tiles'])[i:i + 2], 16) == 65 for i in range(0, 480, 2)]
        with application(profile, 'level-28') as (child, window):
            open_classic()
            driver.wait(contains='Level 28 / ')
            for width, height in ((390, 844), (844, 390)):
                subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
                subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True)
                for tenths in (10, 11, 13, 15):
                    driver.key('0', control=True)
                    for _ in range(tenths - 10):
                        driver.key('=', control=True)
                    deadline = time.monotonic() + 10
                    while True:
                        nodes = driver.tree()
                        screen = nodes[0]
                        if abs(screen['width'] - width * 10 / tenths) < 1.5:
                            break
                        assert time.monotonic() < deadline, screen
                    driver.wait_idle(frames=6)
                    nodes = driver.tree()
                    player = next(n for n in nodes if n['kind'] == 'image' and n['label'] == 'Shovey' and n['visible'])
                    landscape = width > height
                    columns, rows = (20, 12) if landscape else (12, 20)
                    boards = [n for n in nodes if n['kind'] == 'box' and n['visible'] and n['height'] > 0 and
                              abs(n['width'] / n['height'] - columns / rows) < .01 and
                              n['x'] <= player['x'] < n['x'] + n['width'] and
                              n['y'] <= player['y'] < n['y'] + n['height']]
                    board = max(boards, key=lambda n: n['width'] * n['height'])
                    assert int(subprocess.check_output(['xdotool', 'getwindowpid', window])) == child.pid
                    path = output / f'{width}x{height}-{tenths * 10}.png'
                    subprocess.run(['import', '-window', window, str(path)], check=True, timeout=10)
                    picture = Image.open(path).convert('RGB')
                    scale = picture.width / screen['width']
                    cell = board['width'] / columns
                    # The abyss is drawn as a cliff, with rock under its far
                    # edge, so it is not one flat colour. A seam is a line
                    # between two joined abyss cells that is brighter than
                    # the abyss a quarter cell inside both of them.
                    def brightness(x, y):
                        return sum(picture.getpixel((round(x), round(y))))
                    seams = 0
                    bad = []
                    for at, is_abyss in enumerate(abyss):
                        if not is_abyss:
                            continue
                        for neighbor in (at + 1 if at % 12 < 11 else -1, at + 12 if at < 228 else -1):
                            if neighbor < 0 or not abyss[neighbor]:
                                continue
                            def center(index):
                                return (index // 12 + .5, 11 - index % 12 + .5) if landscape else (index % 12 + .5, index // 12 + .5)
                            a, b = center(at), center(neighbor)
                            x = (board['x'] - screen['x'] + (a[0] + b[0]) * cell / 2) * scale
                            y = (board['y'] - screen['y'] + (a[1] + b[1]) * cell / 2) * scale
                            # Across the seam, from inside one cell to inside the other.
                            across = ((b[0] - a[0]) * cell * scale / 4, (b[1] - a[1]) * cell * scale / 4)
                            seams += 1
                            # Rock speckle varies from pixel to pixel, so a
                            # seam is judged along a stretch of the line.
                            line = inside = 0
                            stretch = range(-round(cell * scale / 4), round(cell * scale / 4) + 1)
                            for along in stretch:
                                sx = x + (along if across[0] == 0 else 0)
                                sy = y + (along if across[1] == 0 else 0)
                                inside += max(brightness(sx - across[0], sy - across[1]), brightness(sx + across[0], sy + across[1]))
                                line += max(brightness(sx + step * (across[0] != 0), sy + step * (across[1] != 0)) for step in (-1, 0, 1))
                            if line / len(stretch) > inside / len(stretch) + 45:
                                bad.append((round(x), round(y), line // len(stretch), inside // len(stretch)))
                    assert seams, 'Level 28 needs adjacent abyss cells for this regression'
                    assert not bad, f'{path.name}: pale abyss seams: {bad[:5]}'
    print('Level 28: no internal abyss lines in portrait or landscape at 100%, 110%, 130% and 150% scale')


if __name__ == '__main__':
    main()
