"""Exercise the production cover header and shop routes on a private display."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from world_map_test_support import assert_fullscreen_map, enter_classic_map, start_map_destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
    root = Path(__file__).resolve().parents[1]
    local = root / 'build/player'
    if args.binary.resolve() == local / 'linux/shovey':
        for name in ('shovey.zx', 'shovey.json'):
            current, staged = local / name, args.binary.resolve().parent / name
            assert (current.is_file() and staged.is_file() and
                    hashlib.sha256(current.read_bytes()).digest() == hashlib.sha256(staged.read_bytes()).digest()), (
                'The UI test package is stale. Stage the current collection with '
                'KRYON_TEST_DRIVER=1 python3 scripts/player.py linux before testing.')
    output = root / 'work/header-layout-ui-test'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve()))
    from ui_driver import UiDriver

    catalog = json.loads((root / 'apps.json').read_text())['apps']

    def select_cover(action, direction):
        assert sum(entry['cover']['action'] == ("internal" if action == "Open" else action.lower()) for entry in catalog) == 1
        for index in range(len(catalog)):
            if driver.find(label=action, role='button'):
                return action
            if action == 'Play' and driver.find(key=49224, role='button'):
                return driver.wait(key=49222,role='button')['label']
            if index + 1 < len(catalog):
                driver.press(label=direction, role='button')
                driver.wait_idle(frames=3, timeout=5)
        raise AssertionError(f'{action} cover missing from the {len(catalog)}-entry catalog')

    def separated(a, b):
        return (a['x'] + a['width'] <= b['x'] or b['x'] + b['width'] <= a['x'] or
                a['y'] + a['height'] <= b['y'] or b['y'] + b['height'] <= a['y'])

    def without_game_shortcuts():
        for key in (61000, 61001, 61002, 61003):
            assert not driver.find(key=key), f'In-game shortcut leaked: {key}'

    for width, height in ((320, 640), (480, 820), (960, 600)):
        print(f"header {width}x{height}: start", flush=True)
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
                    driver.wait(key=49224, role='button', timeout=60)
                    play = driver.wait(key=49222,role='button')
                    assert play['label'] == 'Level 1', play
                    driver.wait_gone(key=49401, role='button', timeout=20)
                    if driver.find(label='Download new levels when they come out?', role='text'):
                        driver.press(label='Not now', role='button')
                    windows = subprocess.check_output(
                        ['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
                    assert len(windows) == 1
                    window = windows[0]
                    assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                    subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True, timeout=20)
                    subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True, timeout=20)
                    deadline = time.monotonic() + 10
                    while driver.tree()[0]['width'] != width:
                        assert time.monotonic() < deadline, 'Window did not resize'
                        time.sleep(.05)
                    play = driver.wait(key=49222,role='button')
                    levels = driver.wait(key=49224,role='button')
                    assert play['y'] == levels['y'] and play['height'] == levels['height'] == 64
                    assert levels['x']+levels['width']+8 == play['x']
                    market = driver.wait(key=49200, role='button')
                    chest = driver.wait(key=49202, role='button')
                    book = driver.wait(key=49208, role='button')
                    profile = driver.wait(key=49204, role='button')
                    assert book['x'] + book['width'] + 4 == profile['x']
                    assert book['y'] == profile['y']
                    assert chest['x'] == market['x'] and chest['y'] >= market['y'] + market['height']
                    coins = driver.wait(key=49211, role='text', label='20')
                    dew = driver.wait(key=49213, role='text')
                    assert coins['x'] > market['x'] + market['width'] and dew['x'] == coins['x']
                    assert dew['y'] > coins['y']
                    assert not driver.find(key=49206), 'Guest leaderboard must be hidden'
                    for button in (book, profile):
                        assert separated(coins, button) and separated(dew, button)
                    logos = [node for node in driver.tree() if node['kind'] == 'image' and
                             119 <= node['y'] <= 121 and node['width'] <= 361]
                    assert logos, 'Compact cover logo is missing'
                    for logo in logos:
                        assert separated(logo, market) and separated(logo, chest)
                        assert logo['width'] <= (width * .58 + 1 if width < 600 else 361)
                    subprocess.run(['import', '-window', window, str(output / f'{width}.png')], check=True, timeout=20)
                    driver.press(key=49224, role='button')
                    enter_classic_map(driver)
                    start_map_destination(driver, 1)
                    driver.wait_gone(key=49401, role='button', timeout=20)
                    driver.wait(label='How do you want to move?', role='text')
                    without_game_shortcuts()
                    driver.press(label='Swipe and tap', role='button')
                    driver.wait_gone(label='How do you want to move?', role='text')
                    driver.wait(key=20602, role='text', label='Clear the tasks, then go home.')
                    assert not driver.find(key=20601, role='text'), 'Repeated Pip heading returned'
                    assert not driver.find(key=20616, role='text'), 'Repeated tap instruction returned'
                    subprocess.run(['import', '-window', window, str(output / f'gameplay-tutorial-{width}.png')], check=True, timeout=20)
                    if driver.find(label='Got it', role='button'):
                        driver.press(label='Got it', role='button')
                        driver.wait_gone(label='Got it', role='button')
                    print("header: toolbar ready", flush=True)
                    buttons = [driver.wait(key=key, role='button') for key in (20022, 20016, 20017, 20907)]
                    for button in buttons:
                        assert button['width'] == 44 and button['height'] == 44, button
                        assert button['y'] == buttons[0]['y'], buttons
                        assert 0 <= button['x'] <= width - 44, button
                    assert not driver.find(key=20001, role='text'), 'Level counter returned to gameplay'
                    book_button = driver.wait(key=20820, role='button')
                    for button in buttons: assert separated(book_button, button)
                    subprocess.run(['import', '-window', window, str(output / f'gameplay-{width}.png')], check=True, timeout=20)
                    assert buttons[-1]['label'] == 'Settings'
                    assert buttons[-1]['x'] == width - 52, 'Settings must replace sound at the top right'
                    assert not driver.find(key=20023, role='button'), 'Sound belongs inside Settings'
                    driver.press(key=20907, role='button')
                    sound_before = driver.wait(key=20702, role='button')['label']
                    driver.press(key=20702, role='button')
                    assert driver.wait(key=20702, role='button')['label'] != sound_before
                    driver.press(key=20702, role='button')
                    driver.press(key=20704, role='button')
                    driver.press(key=20016, role='button')
                    driver.wait_idle(frames=3, timeout=5)
                    driver.wait(key=20017, label='Hint · 3', role='button')
                    driver.wait(key=20911, label='3', role='text')
                    driver.press(key=20017, role='button')
                    driver.wait(key=20017, label='Hint · 2', role='button')
                    driver.wait(key=20911, label='2', role='text')
                    assert driver.find(label='Wall', role='image'), 'Hint modal hid the board'
                    assert not driver.find(key=20903, role='button'), 'Hint reveal still requires a second tap'
                    assert not driver.find(key=20904, role='button'), 'Shop should appear only when hints run out'
                    advice = driver.wait(key=20900 * 65599 + 3, role='text')['label']
                    print(f"header: advice {advice!r}", flush=True)
                    assert 'Next moves:' in advice and 'Next target:' in advice, repr(advice)
                    subprocess.run(['import', '-window', window, str(output / f'hint-modal-{width}.png')], check=True, timeout=20)
                    # The board remains visible but input cannot leak through the modal.
                    player_before = driver.find(label='Shovey', role='image')
                    assert player_before, 'Hint modal removed Shovey'
                    driver.key('left')
                    driver.wait_idle(frames=4, timeout=5)
                    assert driver.find(label='Shovey', role='image') == player_before
                    driver.press(key=20905, role='button')
                    driver.wait_gone(key=20905, role='button')
                    driver.press(key=20017, role='button')
                    driver.wait(key=20017, label='Hint · 2', role='button')
                    assert driver.wait(key=20900 * 65599 + 3, role='text')['label'] == advice, 'Reopening charged a second hint'
                    driver.press(key=20905, role='button')
                    if width == 320:
                        print("header: resize to short landscape", flush=True)
                        subprocess.run(['xdotool', 'windowsize', '--sync', window, '960', '360'], check=True, timeout=20)
                        driver.wait_idle(frames=8, timeout=5)
                        driver.press(key=20907, role='button')
                        driver.wait(label='Touch controls', role='text')
                        assert driver.find(label='Wall', role='image'), 'Settings hid the board'
                        assert not driver.find(key=20006), 'Guide text should be collapsed'
                        subprocess.run(['import', '-window', window, str(output / 'settings-landscape.png')], check=True, timeout=20)
                        driver.press(key=20704, role='button')
                        driver.wait(key=20016, role='button')
                        subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True, timeout=20)
                        driver.wait_idle(frames=8, timeout=5)
                    elif width == 480:
                        driver.press(key=20907, role='button')
                        driver.wait(label='Touch controls', role='text')
                        subprocess.run(['import', '-window', window, str(output / 'settings-480.png')], check=True, timeout=20)
                        driver.press(key=20703, role='button')
                        driver.wait(key=20705, label='This level', role='button')
                        assert driver.find(label='Clear the tasks, then go home.', role='text')
                        assert not driver.find(label='Push the ball into its hole, then go home.', role='text'), 'Level guide included an absent mechanic'
                        assert not driver.find(key=20006), 'The long text guide returned'
                        subprocess.run(['import', '-window', window, str(output / 'guide-480.png')], check=True, timeout=20)
                        driver.press(key=20706, role='button')
                        driver.wait(label='Push the ball into its hole, then go home.', role='text')
                        subprocess.run(['import', '-window', window, str(output / 'guide-all-480.png')], check=True, timeout=20)
                        driver.press(key=20704, role='button')
                        driver.wait(label='Touch controls', role='text')
                        driver.key('escape')
                        driver.wait(key=20016, role='button')
                    driver.wait(key=20016, role='button')
                    driver.press(key=20016, role='button')
                    driver.wait(key=20016, role='button')
                    driver.press(key=20017, role='button')
                    driver.wait(key=20017, label='Hint · 2', role='button')
                    driver.press(key=20905, role='button')
                    driver.press(key=20820, role='button')
                    driver.wait(label='Collectibles', role='text')
                    assert not driver.find(label='Still hidden', role='text')
                    assert not driver.find(label='Level 15', role='text')
                    driver.press(key=64001, role='button')

                    next_level = 1
                    if width == 320:
                        route = json.loads((root / 'levels/approved.json').read_text())['levels'][0]['solution']
                        directions = {'0': (-1, 0), '1': (0, -1), '2': (1, 0), '3': (0, 1)}
                        for action in route:
                            dx, dy = directions[action]
                            me = driver.wait(label='Shovey')
                            x = me['x'] + me['width'] * (.5 + dx)
                            y = me['y'] + me['height'] * (.5 + dy)
                            for down in (False, True, False):
                                driver.pointer(x, y, down=down)
                                driver.wait_idle(frames=1, timeout=1)
                            driver.release_pointer()
                            driver.wait_idle(frames=3, timeout=2)
                        driver.wait(label='Level 1 complete', role='text')
                        driver.wait(key=20909, role='button', label='Next')
                        driver.wait_idle(frames=2, timeout=2)
                        assert not driver.find(key=20908, role='text'), 'Repeated results instruction returned'
                        subprocess.run(['import', '-window', window, str(output / f'results-{width}.png')], check=True, timeout=20)
                        driver.press(key=20909, role='button')
                        driver.wait_gone(label='Level 1 complete', role='text')
                        driver.wait(key=20022, role='button')
                        next_level = 2
                    back = driver.wait(key=20022, label='Back', role='button')
                    assert not driver.find(key=20002, visible=True), 'Redundant gameplay Levels control returned'
                    without_game_shortcuts()
                    driver.press(key=20022, role='button')
                    assert_fullscreen_map(driver)
                    # Grid selection marks completion. The played card stays visible and available.
                    card = driver.wait(key=33000 + next_level, role='button')
                    assert card['enabled'], 'The played level is not available after Back'
                    without_game_shortcuts()
                    driver.press(key=20022, role='button')
                    driver.wait(key=49200, role='button')
                    select_cover('Open', 'Next')
                    driver.wait(label='Open', role='button')
                    driver.wait_idle(frames=3, timeout=5)
                    editor_logos = [node for node in driver.tree() if node['kind'] == 'image' and
                                    119 <= node['y'] <= 121 and node['width'] <= 361]
                    assert editor_logos and any('Editor' in node['label'] for node in editor_logos)
                    assert not driver.find(label='Editor', role='text'), 'Redundant caption returned'
                    subprocess.run(['import', '-window', window, str(output / f'{width}-editor.png')], check=True, timeout=20)
                    classic_action = select_cover('Play', 'Previous')
                    driver.wait(label=classic_action, role='button')
                    for key in (49200, 49202):
                        driver.press(key=key, role='button')
                        driver.wait(key=61101, role='button', timeout=60)
                        if key == 49202:
                            driver.wait(key=63021, role='text', label='25')
                            driver.wait(key=63040,visible=True)
                            assert not driver.find(key=63001, role='text'), 'Chest paragraph returned'
                            subprocess.run(['import', '-window', window, str(output / f'chest-{width}.png')], check=True, timeout=20)
                            driver.press(key=63002, role='button')
                            wait = driver.wait(key=63002, role='button', label='Tomorrow')
                            assert not wait['enabled'], 'Claim must be disabled after success'
                            driver.wait_gone(key=63021, role='text')
                            driver.wait_gone(key=63040,visible=True)
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
    print('Header and compact-copy local UI test passed: 320/480/960px layouts, 44px gameplay controls, sound/hints/restart/book, compact clear titles, stored guest coins, Dew readout, title-only Market/Chest, Back routing and Profile navigation')


if __name__ == '__main__':
    main()
