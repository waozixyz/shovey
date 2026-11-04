"""Run the standalone Shovey app privately: its covers, Classic and Editor
opening directly from them, and independent saves."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from world_map_test_support import assert_fullscreen_map, start_map_destination




LEVEL_UPDATES = 'Download new levels when they come out?'


def assert_no_progress_wait(driver):
    """Account progress merges quietly: no screen says it is loading it."""
    for node in driver.tree():
        text = f"{node.get('label') or ''}\n{node.get('detail') or ''}".lower()
        assert 'account progress' not in text, node

def answer_cover_question(driver):
    """Shovey asks once on its covers whether games
    download new levels; tests keep the levels they ship with. The question
    shows in the covers' first frame."""
    driver.wait(label='Play', role='button', timeout=60)
    # The question follows the collection's records, which can load a frame
    # after Play first appears; let the covers settle before looking.
    driver.wait_idle(frames=4)
    assert_no_progress_wait(driver)
    if driver.find(label=LEVEL_UPDATES, role='text'):
        driver.press(label='Not now', role='button')
        driver.wait_gone(label=LEVEL_UPDATES, role='text')



def answer_level_updates(driver, timeout=20):
    """An installed Shovey first asks once whether to download new levels;
    tests keep the levels it ships with. Returns once a level takes input
    or asks how to move."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if driver.find(label=LEVEL_UPDATES, role='text'):
            driver.press(label='Not now', role='button')
            driver.wait_gone(label=LEVEL_UPDATES, role='text')
            return
        if driver.find(label='How do you want to move?', role='text') or driver.find(label='Restart', role='button'):
            return
        time.sleep(0.05)

def wait_level_one(driver, classic_levels):
    """Level 1 of the campaign. The live campaign on the server may already
    hold levels published after this checkout, so it is never shorter."""
    deadline = time.monotonic() + 30
    while not driver.find(contains='Level 1 / ', role='text'):
        if driver.find(key=20105, visible=True):
            assert_fullscreen_map(driver)
            assert_no_progress_wait(driver)
            start_map_destination(driver, 1)
            break
        assert time.monotonic() < deadline, 'Neither map nor level opened'
        time.sleep(.05)
    label = driver.wait(contains='Level 1 / ', role='text')['label']
    assert label.startswith('Level 1 / ') and int(label.rsplit(' ', 1)[1]) >= classic_levels, label

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--inbe-source', type=Path, required=True)
    parser.add_argument('--classic-levels', type=int, help='Expected campaign length of an already built artifact')
    parser.add_argument('--map-only', action='store_true', help='Run the focused Classic map navigation and selection test')
    parser.add_argument('--map-resume-only', action='store_true', help='Run the focused same-level map Play resume regression')
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
    root = Path(__file__).resolve().parents[1]
    output = root / ('work/map-play-resume-test' if args.map_resume_only else
                     'work/classic-map-ui-test' if args.map_only else 'build/shovey-standalone-ui-test')
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    # Classic's heading counts its levels, which the published campaign lists.
    classic_levels = args.classic_levels or len(json.loads((root / 'levels/approved.json').read_text())['levels'])
    output.mkdir(parents=True, exist_ok=True)
    for path in (root / 'src/locales').glob('*.txt'):
        assert '[shovey_progress_loading]' not in path.read_text(), path
    sys.path.insert(0, str(args.inbe_source / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')

    @contextlib.contextmanager
    def application(profile, name):
        log_path = output / (name + '.log')
        with log_path.open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                                     env=os.environ | driver.environment() |
                                     {'ARCADE_DATA': str(profile), 'LANG': 'en_US.UTF-8'},
                                     stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                driver.wait(label='Play', role='button')
                driver.wait(label='Next', role='button')
                yield child
            finally:
                if child.poll() is None:
                    child.terminate()
                returncode = child.wait(timeout=10)
                (output / (name + '.exit.json')).write_text(json.dumps({'pid': child.pid, 'returncode': returncode}) + '\n')

    def move_until_saved(record):
        before = record.read_bytes() if record.exists() else b''
        for key in ('left', 'up', 'right', 'down'):
            driver.key(key)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if record.exists() and record.read_bytes() != before:
                    return record.read_bytes()
                time.sleep(.05)
        raise AssertionError(f'No move was saved to {record}')

    def campaign_progress(data):
        # Animals keep wandering while the window rotates. Campaign unlocks,
        # completion marks, player state and board identity must stay intact.
        text = data.decode()
        assert text[:2] in ('C1', 'C2', 'C3', 'C4', 'C5', 'C6')
        header, marks = (6, 1000) if text[:2] in ('C5', 'C6') else (4, 175)
        state = text[header + marks:]
        assert state[:2] in ('P1', 'P2', 'P3')
        assert set(text[header:header + marks]) <= {'0', '1'}
        return (int(text[2:header], 16), text[header:header + marks], state[:32]), text[-8:]

    def swipe_beside_board_until_saved(record):
        """A swipe on the game screen moves Shovey even where the board is not."""
        nodes = driver.tree()
        screen = nodes[0]
        # The board is the box Shovey stands in, not the slate behind the screen.
        shovey_image = next(node for node in nodes if node['kind'] == 'image' and node['label'] == 'Shovey')
        sx, sy = shovey_image['x'] + shovey_image['width'] / 2, shovey_image['y'] + shovey_image['height'] / 2
        board = max((node for node in nodes if node['kind'] == 'box' and node['visible'] and node['key'] != 19990 and
                     node['x'] <= sx <= node['x'] + node['width'] and node['y'] <= sy <= node['y'] + node['height']),
                    key=lambda node: node['width'] * node['height'])
        left_gap = board['x'] - screen['x']
        below_gap = screen['y'] + screen['height'] - (board['y'] + board['height'])
        if left_gap >= below_gap:
            x, y = screen['x'] + left_gap / 2, board['y'] + board['height'] / 2
        else:
            x, y = board['x'] + board['width'] / 2, board['y'] + board['height'] + below_gap / 2
        # The portrait layout has a 24 px margin; a vertical swipe fits there.
        assert max(left_gap, below_gap) > 8, f'no room beside the board: {board} in {screen}'
        before = record.read_bytes()
        for dx, dy in ((-80, 0), (0, -80), (80, 0), (0, 80)):
            driver.drag((x, y), (x + dx, y + dy))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if record.read_bytes() != before:
                    return
                time.sleep(.05)
        raise AssertionError(f'A swipe beside the board at {x}, {y} moved nothing')

    def board_and_player(board_key=22000):
        board = driver.find(key=board_key, visible=True)[0]
        players = driver.find(label='Shovey', role='image', visible=True)
        assert len(players) == 1, 'Only the player may be labelled Shovey; terrain must have its own name'
        player = players[0]
        return board, player

    def resize_owned_window(child, width, height):
        windows = subprocess.check_output(
            ['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
        assert len(windows) == 1
        window = windows[0]
        owner = subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip()
        assert owner == str(child.pid)
        subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
        subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            screen = driver.tree()[0]
            if (screen['width'], screen['height']) == (width, height):
                driver.wait_idle(frames=3)
                return window
            time.sleep(.05)
        raise AssertionError('Shovey did not adopt the resized window')

    def swipe_in_visible_direction(board_key=22000):
        board, player = board_and_player(board_key)
        before = UiDriver.center(player)
        start = (board['x'] + board['width'] / 2, board['y'] + board['height'] / 2)
        for dx, dy in ((-100, 0), (0, -100), (100, 0), (0, 100)):
            driver.drag(start, (start[0] + dx, start[1] + dy))
            deadline = time.monotonic() + .8
            while time.monotonic() < deadline:
                _, player = board_and_player(board_key)
                after = UiDriver.center(player)
                moved_x, moved_y = after[0] - before[0], after[1] - before[1]
                if abs(moved_x) + abs(moved_y) > 2:
                    if dx:
                        assert moved_x * dx > 0 and abs(moved_y) < 2, 'horizontal swipe moved in another direction'
                    else:
                        assert moved_y * dy > 0 and abs(moved_x) < 2, 'vertical swipe moved in another direction'
                    return
                time.sleep(.05)
        raise AssertionError('No visible swipe direction moved Shovey')

    def press_pad_in_visible_direction(pad):
        """A short press on an arm steps Shovey that way on the screen."""
        third = pad['width'] / 3
        arms = {(-1, 0): (pad['x'] + third / 2, pad['y'] + third * 1.5), (0, -1): (pad['x'] + third * 1.5, pad['y'] + third / 2),
                (1, 0): (pad['x'] + third * 2.5, pad['y'] + third * 1.5), (0, 1): (pad['x'] + third * 1.5, pad['y'] + third * 2.5)}
        for (dx, dy), (x, y) in arms.items():
            before = UiDriver.center(board_and_player()[1])
            driver.pointer(x, y)
            driver.pointer(x, y, down=True)
            driver.pointer(x, y, down=False)
            driver.release_pointer()
            deadline = time.monotonic() + .8
            while time.monotonic() < deadline:
                after = UiDriver.center(board_and_player()[1])
                moved_x, moved_y = after[0] - before[0], after[1] - before[1]
                if abs(moved_x) + abs(moved_y) > 2:
                    if dx:
                        assert moved_x * dx > 0 and abs(moved_y) < 2, 'a horizontal arm moved Shovey another way'
                    else:
                        assert moved_y * dy > 0 and abs(moved_x) < 2, 'a vertical arm moved Shovey another way'
                    return
                time.sleep(.05)
        raise AssertionError('No arm of the movement pad moved Shovey')

    def assert_map_terrain_fills_height():
        nodes = driver.tree()
        viewport = next(node for node in nodes if node.get('key') == 20105)
        water = next(node for node in nodes if node.get('key') == 59999)
        # Fixed authored water fills the viewport between regional paintings.
        # Image panels alone need not cover every point in that water.
        assert water['x'] <= viewport['x'] + 1 and water['y'] <= viewport['y'] + 1
        assert water['x'] + water['width'] >= viewport['x'] + viewport['width'] - 16
        assert water['y'] + water['height'] >= viewport['y'] + viewport['height'] - 16
        panels = [node for node in nodes if node.get('kind') == 'image' and 60000 <= node.get('key', 0) < 60100]
        assert any(panel['visible'] for panel in panels), 'Focused map has no visible regional painting'

    def overlaps(a, b):
        return a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] and \
            a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height']

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
        profile = Path(temporary)
        classic = profile / 'games/arcade.shovey/records/local.campaign'
        account_progress = profile / 'entity/records/local/game-progress/fd65a3d7ac3d5ceb2d4d96cc5224a740.json'
        if args.map_resume_only:
            with application(profile, 'focused-play'):
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                wait_level_one(driver, classic_levels)
                answer_level_updates(driver)
                if driver.find(label='How do you want to move?', role='text'):
                    driver.press(label='Swipe and tap')
                    driver.wait_gone(label='How do you want to move?', role='text')
                if driver.find(label='Got it', role='button'):
                    driver.press(label='Got it', role='button')
                    driver.wait_gone(label='Got it', role='button')
                move_until_saved(classic)
                saved = campaign_progress(classic.read_bytes())
                before_board, before_player = board_and_player()
                driver.press(label='Back', role='button')
                driver.wait(label='Play', role='button')
            with application(profile, 'focused-resume'):
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                wait_level_one(driver, classic_levels)
                after_board, after_player = board_and_player()
                before = UiDriver.center(before_player)
                after = UiDriver.center(after_player)
                before_cell = ((before[0] - before_board['x']) / before_board['width'],
                               (before[1] - before_board['y']) / before_board['height'])
                after_cell = ((after[0] - after_board['x']) / after_board['width'],
                              (after[1] - after_board['y']) / after_board['height'])
                assert abs(after_cell[0] - before_cell[0]) < .01 and abs(after_cell[1] - before_cell[1]) < .01, \
                    ('same-level map Play restarted the board', before_cell, after_cell)
                assert campaign_progress(classic.read_bytes()) == saved
                driver.press(label='Restart', role='button')
                deadline = time.monotonic() + 5
                while campaign_progress(classic.read_bytes()) == saved:
                    assert time.monotonic() < deadline, 'explicit Restart is blocked after map resume'
                    time.sleep(.05)
            print('Focused same-level map Play resume local test passed: moved board/moves/save preserved, explicit Restart resets')
            return
        with application(profile, 'play') as child:
            assert not driver.find(label='Arcade', role='text')
            # The covers ask once whether games download new levels.
            driver.wait(label=LEVEL_UPDATES, role='text')
            answer_cover_question(driver)
            assert (profile / 'games/arcade.shovey-player/records/level-updates').read_text() == 'off'
            driver.press(label='Play', role='button')
            wait_level_one(driver, classic_levels)
            # Desktop play uses its default controls; a chooser may appear on touch hosts.
            answer_level_updates(driver)
            if driver.find(label='How do you want to move?', role='text'):
                driver.press(label='Swipe and tap')
                driver.wait_gone(label='How do you want to move?', role='text')
            if driver.find(label='Got it', role='button'):
                driver.press(label='Got it', role='button')
                driver.wait_gone(label='Got it', role='button')
            assert not driver.find(label='Continue', role='button'), 'Classic must open straight on a level'
            assert driver.find(label='Shovey', role='image', visible=True), 'Shovey must be drawn as a picture'
            assert driver.find(label='Back', role='button', visible=True), 'Classic lacks its return control'
            driver.press(label='Mute', role='button')
            driver.wait(label='Unmute', role='button')
            assert (profile / 'games/arcade.shovey-player/records/sound').read_text() == 'muted'
            driver.press(label='Unmute', role='button')
            driver.wait(label='Mute', role='button')
            assert (profile / 'games/arcade.shovey-player/records/sound').read_text() == 'on'
            driver.press(label='Levels', role='button')
            assert_fullscreen_map(driver)
            window = resize_owned_window(child, 390, 844)
            portrait_marker = driver.wait(key=33001, role='button', visible=True)
            assert portrait_marker['width'] >= 48 and portrait_marker['height'] >= 48
            assert not driver.find(key=34001) and not driver.find(key=34002) and not driver.find(key=34003), \
                'Undiscovered rooms leaked onto the journey'
            driver.key('end')
            locked = driver.wait(key=33004, role='button', visible=True)
            assert not locked['enabled'], 'A future waypoint became playable'
            # The whole map browses at any progress; later waypoints stay locked.
            assert not any(33005 <= node.get('key', 0) <= 33175 and node.get('enabled') for node in driver.tree()), \
                'Fresh progress made a later waypoint playable'
            driver.key('enter')
            # End focuses the last available level, while locked previews remain disabled.
            wait_level_one(driver, classic_levels)
            driver.press(label='Levels', role='button')
            assert_fullscreen_map(driver)
            driver.key('home')
            # Movement cannot enter the locked previews.
            for _ in range(3):
                driver.key('up')
            middle = driver.wait(key=33004, role='button', visible=True)
            assert not middle['enabled'] and driver.wait(key=33001, role='button')['selected'], middle
            before_y = middle['y']
            driver.drag((24, 240), (24, 540))
            driver.wait_idle(frames=3)
            moved = driver.find(key=33004, role='button', visible=True)
            assert not moved or moved[0]['y'] >= before_y - 1, 'Touch dragging escaped the public camera bounds'
            driver.key('home')
            driver.wait(key=33001, role='button', visible=True)
            assert_map_terrain_fills_height()
            subprocess.run(['import', '-window', window, str(output / 'level-selector-portrait.png')], check=True)
            window = resize_owned_window(child, 960, 600)
            # The same portrait journey stays centered in a wide viewport;
            # waypoints remain touch-sized rather than becoming board cards.
            landscape_marker = driver.wait(key=33001, role='button', visible=True)
            assert landscape_marker['width'] >= 48 and landscape_marker['height'] >= 48
            viewport = driver.find(key=20105, visible=True)[0]
            marker_x = landscape_marker['x'] + landscape_marker['width'] / 2
            assert abs(marker_x - (viewport['x'] + viewport['width'] / 2)) <= viewport['width'] * .15, \
                'Focused waypoint was not revealed by the horizontal camera'
            assert landscape_marker['selected'] and landscape_marker['enabled']
            assert_map_terrain_fills_height()
            subprocess.run(['import', '-window', window, str(output / 'level-selector-landscape.png')], check=True)
            # One press keeps the focused waypoint selected and Play opens it;
            # two quick presses on it would open it directly.
            start_map_destination(driver, 1)
            wait_level_one(driver, classic_levels)
            driver.press(label='Levels', role='button')
            assert_fullscreen_map(driver)
            # Back from the level list returns to the level, then to the covers.
            driver.press(key=20022)
            wait_level_one(driver, classic_levels)
            assert not driver.find(label='Continue', role='button', visible=True)
            driver.press(label='Back', role='button')
            driver.wait(label='Play', role='button')
            if args.map_only:
                print('Classic map local UI test passed: 390x844 and 960x600, keyboard 1/4, locked previews, touch scrolling, selection and Back')
                return
            answer_cover_question(driver)
            driver.press(label='Play', role='button')
            wait_level_one(driver, classic_levels)
            move_until_saved(classic)
            swipe_beside_board_until_saved(classic)
            # Rotation changes presentation without replacing the saved game.
            swipe_boards = {}
            for width, height, columns, rows in ((960, 600, 20, 12), (480, 820, 12, 20)):
                saved = campaign_progress(classic.read_bytes())
                window = resize_owned_window(child, width, height)
                board, player = board_and_player()
                swipe_boards[width, height] = board
                assert abs(board['width'] / board['height'] - columns / rows) < .01
                assert board['x'] >= 0 and board['y'] >= 0
                assert board['x'] + board['width'] <= width and board['y'] + board['height'] <= height
                assert campaign_progress(classic.read_bytes()) == saved, 'rotation changed or reset the saved game'
                orientation = 'landscape' if width > height else 'portrait'
                subprocess.run(['import', '-window', window, str(output / (orientation + '.png'))], check=True)
                swipe_in_visible_direction()
            # The movement pad floats over the board's bottom left corner: the
            # board keeps its place and size, and the pad's arms step Shovey.
            driver.press(key=20017)
            driver.press(label='Movement pad', role='button')
            driver.press(key=20017)
            driver.wait(key=20040, role='button')
            assert (profile / 'games/arcade.shovey-player/records/controls').read_text() == 'on'
            for width, height in ((480, 820), (960, 600)):
                resize_owned_window(child, width, height)
                board = board_and_player()[0]
                pad = driver.find(key=20040, visible=True)[0]
                before = swipe_boards[width, height]
                assert all(abs(board[field] - before[field]) <= 1 for field in ('x', 'y', 'width', 'height')), \
                    ('the pad moved the board', width, height, before, board)
                assert pad['x'] < width / 3 and height * .7 < pad['y'] + pad['height'] <= height, ('pad corner', pad)
                assert overlaps(pad, board), ('the pad should float over the board', pad, board)
                press_pad_in_visible_direction(pad)
            # Back to swipe and tap: the pad goes and the board stays put.
            driver.press(key=20017)
            driver.press(label='Swipe and tap', role='button')
            driver.press(key=20017)
            driver.wait_gone(key=20040, role='button')
            assert (profile / 'games/arcade.shovey-player/records/controls').read_text() == 'off'
            board = board_and_player()[0]
            assert all(abs(board[field] - swipe_boards[960, 600][field]) <= 1 for field in ('x', 'y', 'width', 'height'))
            swipe_in_visible_direction()
            restart_saved = campaign_progress(classic.read_bytes())
            restarted_board, restarted_player = board_and_player()
            driver.press(label='Restart', role='button')
            deadline = time.monotonic() + 5
            while campaign_progress(classic.read_bytes()) == restart_saved:
                assert time.monotonic() < deadline, 'explicit Restart did not reset the board'
                time.sleep(.05)
            driver.wait_idle(frames=3)
            reset_board, reset_player = board_and_player()
            assert (reset_player['x'], reset_player['y']) != (restarted_player['x'], restarted_player['y']), 'Restart kept the moved player'
            assert (reset_board['width'], reset_board['height']) == (restarted_board['width'], restarted_board['height'])
            move_until_saved(classic)
            moved_board, moved_player = board_and_player()
            assert UiDriver.center(moved_player) != UiDriver.center(reset_player), 'post-Restart move did not move Shovey'
            classic_saved = campaign_progress(classic.read_bytes())
            resize_owned_window(child, 480, 820)
            resume_board, resume_player = board_and_player()
            assert not account_progress.exists(), 'Movement wrote an account progress record'
            assert len(driver.find(label='Back', role='button', visible=True)) == 1, 'Shovey needs one clear Back action'
            driver.press(label='Back', role='button')
            driver.wait(label='Play', role='button')
            driver.press(label='Next', role='button')
            # Island's public cover sits between Classic and the Editor.
            driver.press(label='Next', role='button')
            driver.press(label='Open', role='button')
            # The editor opens on a blank board; Levels lists the creator's
            # own boards under Classic and makes a new one.
            driver.wait(label='New level', role='text')
            driver.press(label='Levels', role='button')
            driver.wait(label='Classic', role='text')
            driver.wait(label='Your levels', role='text')
            assert not any(260000 <= node.get('key', 0) < 264000 for node in driver.tree()), 'Story levels returned to the editor'
            driver.press(label='New level', role='button')
            driver.wait(key=200000, timeout=20)
            driver.wait(label='Play', role='button')
            # Editing follows the device, including portrait screens whose
            # board area becomes wider after reserving the toolbar/palette.
            for width, height in ((390, 844), (844, 390), (580, 600), (480, 820)):
                resize_owned_window(child, width, height)
                board = driver.find(key=200000, visible=True)[0]
                aspect = 5 / 3 if width > height else 3 / 5
                assert abs(board['width'] / board['height'] - aspect) < .01, ('editor paint orientation', width, height, board)
            answer_cover_question(driver)
            driver.press(label='Play', role='button')
            driver.wait(label='Testing', role='text')
            for width, height in ((390, 844), (844, 390), (480, 820)):
                window = resize_owned_window(child, width, height)
                board, player = board_and_player(200000)
                aspect = 5 / 3 if width > height else 3 / 5
                assert abs(board['width'] / board['height'] - aspect) < .01, ('editor play orientation', width, height, board)
                swipe_in_visible_direction(board_key=200000)
            # Escape returns from testing to the board, then leaves the editor.
            driver.key('escape')
            driver.wait(label='Levels', role='button')
            driver.key('escape')
            driver.wait(label='Open', role='button')
        classic_bytes = classic.read_bytes()
        text = classic_bytes.decode()
        header, marks = (6, 1000) if text.startswith(('C5', 'C6')) else (4, 175)
        start = header + marks
        text = text[:2] + f'{2:0{header - 2}x}' + '1' + '0' * (marks - 1) + text[start:]
        text = text[:start + 28] + '01' + text[start + 30:]
        classic.write_text(text)
        with application(profile, 'replay-controls'):
            driver.press(label='Play', role='button')
            start_map_destination(driver, 1)
            driver.wait(contains='Level 1 / ', role='text')
            deadline = time.monotonic() + 5
            while campaign_progress(classic.read_bytes())[0][2][10:18] != '00000000':
                assert time.monotonic() < deadline, 'completed-level replay did not restart'
                time.sleep(.05)
            driver.press(label='Levels', role='button')
            start_map_destination(driver, 2)
            driver.wait(contains='Level 2 / ', role='text')
        classic.write_bytes(classic_bytes)
        with application(profile, 'restore'):
            driver.press(label='Next', role='button')
            driver.press(label='Next', role='button')
            driver.press(label='Open', role='button')
            driver.wait(label='New level', role='text')
            # Escape on the board returns to the editor's cover, which stays selected.
            driver.key('escape')
            driver.wait(label='Open', role='button')
            driver.press(label='Previous', role='button')
            driver.press(label='Previous', role='button')
            answer_cover_question(driver)
            driver.press(label='Play', role='button')
            wait_level_one(driver, classic_levels)
            resumed_board, resumed_player = board_and_player()
            before = UiDriver.center(resume_player)
            after = UiDriver.center(resumed_player)
            before_cell = ((before[0] - resume_board['x']) / resume_board['width'],
                           (before[1] - resume_board['y']) / resume_board['height'])
            after_cell = ((after[0] - resumed_board['x']) / resumed_board['width'],
                          (after[1] - resumed_board['y']) / resumed_board['height'])
            assert abs(after_cell[0] - before_cell[0]) < .01 and abs(after_cell[1] - before_cell[1]) < .01, \
                ('map Play resumed at a different position', before_cell, after_cell)
            assert campaign_progress(classic.read_bytes()) == classic_saved
            assert not account_progress.exists(), 'Restart published an unfinished board'
    print('Standalone Shovey: portrait/landscape boards, swipe directions, the floating movement pad, rotation saves, covers and independent saves passed')


if __name__ == '__main__':
    main()
