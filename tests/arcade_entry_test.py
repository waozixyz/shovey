"""Normal Shovey collection entry, legacy editor records and real library captures.

Run under build-queue. The native player and its verified collection must already
be built; --binary can select a parent's isolated integration fixture.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/arcade-library'



def assert_real_title(driver):
    """The same node-owned title in standalone and Arcade, including its HUD."""
    driver.wait(key=49202, role='button', visible=True, timeout=90)
    driver.wait(key=49204, role='button', visible=True)
    driver.wait(label='Play', role='button', visible=True)
    nodes = driver.tree()
    for key in (49200, 49202, 49204, 49206, 49208, 49210, 49212):
        control = next((n for n in nodes if n['key'] == key and n['visible']), None)
        assert control, ('Title control missing', key)
        screen = nodes[0]
        assert 0 <= control['x'] and control['x'] + control['width'] <= screen['width'], control
        assert 0 <= control['y'] and control['y'] + control['height'] <= screen['height'], control
    assert any(n['kind'] == 'image' and 'title/shovey-' in n.get('detail', '') for n in nodes), 'Node-owned title art missing'
    assert not driver.find(key=20105, visible=True), 'Entry bypassed the title'
    assert not driver.find(key=20510, visible=True), 'Simplified portable title returned'


def exercise_title(driver, width, height):
    windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(driver.process.pid)], text=True).split()
    assert len(windows) == 1
    window = windows[0]
    assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(driver.process.pid)
    subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True)
    subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
    driver.wait_idle(frames=20)
    assert_real_title(driver)
    captures = WORK / 'captures'
    captures.mkdir(exist_ok=True)
    binary_name = Path(driver.process.args[0]).name
    subprocess.run(['import', '-window', window, str(captures / f'{binary_name}-title-{width}x{height}.png')], check=True)
    # A real horizontal swipe changes covers, and Previous returns to Classic.
    nodes = driver.tree()
    screen = nodes[0]
    y = screen['height'] * .55
    driver.drag((screen['width'] * .8, y), (screen['width'] * .2, y))
    driver.wait_idle(frames=30)
    assert not driver.find(label='Play', role='button', visible=True), 'Title swipe did not change covers'
    driver.press(label='Previous', role='button')
    driver.wait_idle(frames=30)
    assert_real_title(driver)
    driver.press(key=49202, role='button')
    driver.wait(key=61101, role='button', visible=True)
    driver.press(key=61101, role='button')
    assert_real_title(driver)
    driver.press(key=49204, role='button')
    driver.wait(label='Account', role='text', visible=True)
    driver.press(label='Back', role='button')
    assert_real_title(driver)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/player/linux/shovey')
    parser.add_argument('--driver-source', type=Path,
                        default=ROOT.parents[1] / 'apps/breeze')
    parser.add_argument('--capture-only', action='store_true', help='Capture an already built game without asserting new entry routing')
    parser.add_argument('--ui', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    subprocess.run(['git', 'check-ignore', '-q', str(WORK)], cwd=ROOT, check=True)
    WORK.mkdir(parents=True, exist_ok=True)
    if not args.ui:
        environment = {key: value for key, value in os.environ.items() if key not in
                       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
                        'SESSION_MANAGER', 'GDK_DISPLAY')}
        environment.update(YUE_DESKTOP_RECOVERY='0', SDL_AUDIODRIVER='dummy', TMPDIR=str(WORK))
        subprocess.run(['xvfb-run', '-a', '-n', '400', '-s', '-screen 0 1800x1400x24',
                        sys.executable, __file__, '--ui', '--binary', str(args.binary.resolve()),
                        '--driver-source', str(args.driver_source.resolve()),
                        *(['--capture-only'] if args.capture_only else [])],
                       cwd=ROOT, env=environment, check=True)
        return
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    from PIL import Image
    from world_map_test_support import private_environment, digest
    driver_source = args.driver_source.resolve()
    sys.path.insert(0, str(driver_source / 'tests' if (driver_source / 'tests/ui_driver.py').is_file() else driver_source))
    from ui_driver import UiDriver
    binary = args.binary.resolve()
    receipt = json.loads(binary.with_name('shovey.json').read_text())
    assert receipt['id'] == 'arcade.shovey-player'
    assert digest(binary.with_name('shovey.zx')) == receipt['sha256']
    children = {item['id']: item for item in receipt['children']}
    for identity, name in receipt.get('local_bundles', {}).items():
        assert name == 'games/' + children[identity]['expected_id'] + '.zx'
        payload = binary.parent / name
        assert payload.stat().st_size == children[identity]['bytes']
        assert digest(payload) == children[identity]['sha256']
    assert children['arcade.shovey-editor']['expected_id'] == 'shovey-editor'
    assert not any('island' in key and 'editor' in key for key in children)
    source = json.loads((ROOT / 'apps.json').read_text())
    assert source['id'] == receipt['id']
    assert any(item['manifest'] == 'src/editor/catalog.json' for item in source['apps'])
    assert json.loads((ROOT / 'src/editor/catalog.json').read_text())['id'] == 'arcade.shovey-editor'
    captures = []

    from world_map_test_support import assert_fullscreen_map, start_map_destination
    from shovey_standalone_ui_test import answer_cover_question

    def classic_cover():
        for _ in range(4):
            if driver.find(label='Play', role='button', visible=True):
                return
            driver.press(label='Previous', role='button')
            driver.wait_idle(frames=8)
        raise AssertionError('Classic artwork cover is missing')

    direct_error = None
    if not args.capture_only:
        with tempfile.TemporaryDirectory(prefix='direct-entry-', dir=WORK) as folder:
            profile = Path(folder)
            records = profile / 'games/arcade.shovey-player/records'
            records.mkdir(parents=True)
            (records / 'level-updates').write_text('off')
            driver = UiDriver(profile / 'driver')
            log_path = WORK / 'direct-entry.log'
            with log_path.open('w') as log:
                child = subprocess.Popen([str(binary), '--app', 'shovey'], cwd=binary.parent,
                    env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
                driver.attach(child, log_path)
                try:
                    assert_real_title(driver)
                    for width, height in ((1440, 900), (720, 1080)):
                        exercise_title(driver, width, height)
                    assert driver.find(label='Shovey', role='image', visible=True), 'Direct entry proper title artwork missing'
                    assert not driver.find(key=20105, visible=True), 'Arcade direct game entry bypassed the proper title'
                    assert not driver.find(key=20510, visible=True), 'Removed Play/Editor title returned'
                    driver.press(label='Play', role='button')
                    assert_fullscreen_map(driver)
                    assert not driver.find(key=20510, visible=True), 'Second title after Play'
                except AssertionError as error:
                    direct_error = str(error)
                    print('Direct game entry FAILED: ' + direct_error, flush=True)
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)

    # Only disposable test records are seeded. Existing owner records are never read.
    with tempfile.TemporaryDirectory(prefix='profile-', dir=WORK) as folder:
        profile = Path(folder)
        records = profile / 'games/arcade.shovey-player/records'
        records.mkdir(parents=True)
        (records / 'level-updates').write_text('off')
        (records / 'controls').write_text('off')
        legacy = profile / 'games/arcade.shovey-editor/records'
        legacy.mkdir(parents=True)
        board = ''.join('0c' if x in (0, 11) or y in (0, 19) else
                        '0a' if (x, y) == (6, 4) else '07' if (x, y) == (6, 15) else '00'
                        for y in range(20) for x in range(12))
        originals = {'classic-levels': 'I1\nnext 2\nlevel 1 0 s 0 - Library continuity\n',
                     'classic-1': 'E1\nboard ' + board + '\nroute 33333333333\n'}
        for name, text in originals.items():
            (legacy / name).write_text(text)
        driver = UiDriver(profile / 'driver')
        campaign = profile / 'games/arcade.shovey/records/local.campaign'

        def position():
            area = driver.find(key=22000, visible=True)[0]
            player = driver.find(label='Shovey', role='image', visible=True)[0]
            return ((player['x'] + player['width'] / 2 - area['x']) / area['width'],
                    (player['y'] + player['height'] / 2 - area['y']) / area['height'])

        def saved_game():
            text = campaign.read_text()
            assert text.startswith(('C5', 'C6'))
            # Campaign unlocks/completions and player/moves are stable even
            # while animals keep animating on the board.
            return text[:1006], text[1006:1038]

        expected_game = None
        expected_position = None
        consent_actions = []

        def open_editor():
            for _ in range(4):
                if driver.find(label='Open', role='button', visible=True):
                    break
                driver.press(label='Next', role='button')
                driver.wait_idle(frames=8)
            driver.press(label='Open', role='button')
            deadline = time.monotonic() + 90
            while not driver.find(label='Levels', role='button', visible=True):
                assert time.monotonic() < deadline, 'Editor did not open through shared Apps'
                # Accept only the normal dialog naming this exact add-on.
                if driver.find(label='Shovey Editor', visible=True):
                    for label in ('Install', 'Download', 'Open'):
                        if driver.find(label=label, role='button', visible=True):
                            driver.press(label=label, role='button')
                            consent_actions.append(label)
                            break
                time.sleep(.05)
        for turn in range(1 if args.capture_only else 2):
            if turn:
                # A prior uninstall keeps the bundled bytes and old drafts.
                # Opening Editor must use the ordinary named install consent.
                state = profile / 'resources/state/arcade.shovey-editor.json'
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text('{"v":1,"installed":0,"favorite":0}')
            consent_start = len(consent_actions)
            log_path = WORK / f'normal-entry-{turn}.log'
            with log_path.open('w') as log:
                child = subprocess.Popen([str(binary)], cwd=binary.parent,
                    env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
                driver.attach(child, log_path)
                try:
                    answer_cover_question(driver)
                    assert_real_title(driver)
                    driver.wait(label='Play', role='button', timeout=90)
                    assert driver.find(label='Shovey', role='image', visible=True), 'Proper title artwork missing'
                    assert not driver.find(key=20105, visible=True), 'Entry bypassed the proper title'
                    assert not driver.find(key=20510, visible=True), 'Removed Play/Editor title returned'
                    if turn == 0:
                        driver.press(label='Play', role='button')
                        assert_fullscreen_map(driver)
                        assert not driver.find(key=20510, visible=True), 'Second title after Play'
                        start_map_destination(driver, 1)
                        driver.wait(contains='Level 1 / ', role='text')
                        if driver.find(label='Got it', role='button'):
                            driver.press(label='Got it', role='button')
                        driver.wait(label='Restart', role='button')
                        # Capture the real owned game window, never a rendered mockup.
                        windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible',
                                                          '--pid', str(child.pid)], text=True).split()
                        assert len(windows) == 1
                        window = windows[0]
                        assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                        for orientation, width, height in [('landscape', 1440, 900), ('portrait', 720, 1080)]:
                            subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True)
                            subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
                            deadline = time.monotonic() + 15
                            while True:
                                screen = driver.tree()[0]
                                if (screen['width'], screen['height']) == (width, height):
                                    break
                                assert time.monotonic() < deadline, 'Game did not resize'
                                time.sleep(.05)
                            driver.wait_idle(frames=8)
                            nodes = driver.tree()
                            assert driver.find(label='Shovey', role='image', visible=True)
                            assert not driver.find(label='Testing', visible=True)
                            assert not driver.find(label='Levels', role='text_field', visible=True)
                            path = (ROOT / 'packaging/library' if args.capture_only else WORK / 'captures') / (orientation + '.png')
                            path.parent.mkdir(parents=True, exist_ok=True)
                            raw = WORK / (orientation + '-raw.png')
                            subprocess.run(['import', '-window', window, str(raw)], check=True)
                            with Image.open(raw) as image:
                                assert image.size == (width, height), (image.size, width, height)
                                rgb = image.convert('RGB')
                                assert sum(hi - lo for lo, hi in rgb.getextrema()) > 120
                                rgb.save(path, optimize=True)
                            captures.append(dict(path=str(path), width=width, height=height,
                                sha256=digest(path), window_pid=child.pid, display=os.environ['DISPLAY'],
                                screen='Classic level 1 gameplay', capture='ImageMagick owned-window XGetImage; lossless RGB PNG',
                                game_sha256=children['arcade.shovey']['sha256']))
                        if args.capture_only:
                            continue
                        initial = position()
                        moved = False
                        for key in ('left', 'up', 'right', 'down'):
                            driver.key(key)
                            deadline = time.monotonic() + 2
                            while time.monotonic() < deadline:
                                if position() != initial:
                                    moved = True
                                    break
                                time.sleep(.05)
                            if moved:
                                break
                        assert moved, 'Game did not move before opening the editor'
                        driver.wait_idle(frames=8)
                        expected_position = position()
                        expected_game = saved_game()
                        driver.press(label='Back', role='button')
                        driver.wait(label='Play', role='button')
                    open_editor()
                    if turn:
                        assert 'Install' in consent_actions[consent_start:], 'Reinstall skipped normal named consent'
                        assert json.loads(state.read_text())['installed'] == 1
                    driver.wait(label='Levels', role='button')
                    driver.press(label='Levels', role='button')
                    driver.wait(label='Library continuity', role='button')
                    driver.press(label='Library continuity', role='button')
                    driver.wait(label='Levels', role='button')
                    driver.key('escape')
                    driver.wait(label='Open', role='button')
                    for name, text in originals.items():
                        assert (legacy / name).read_text() == text, 'Legacy draft changed: ' + name
                    assert not (profile / 'games/arcade.shovey/records/classic-1').exists()
                    # Editor Back resumes this game, and a process restart keeps
                    # both the moved campaign and the original editor draft.
                    classic_cover()
                    driver.press(label='Play', role='button')
                    # Play resumes the level still open in this process; after
                    # a restart it opens the full-screen map first.
                    deadline = time.monotonic() + 30
                    while not driver.find(label='Restart', role='button', visible=True):
                        if driver.find(key=20105, visible=True):
                            start_map_destination(driver, 1)
                            break
                        assert time.monotonic() < deadline, 'Play opened neither the map nor the level'
                        time.sleep(.05)
                    driver.wait(label='Restart', role='button')
                    driver.wait_idle(frames=8)
                    assert saved_game() == expected_game, 'Editor navigation/restart changed the saved game'
                    if not turn:
                        assert all(abs(a - b) < .01 for a, b in zip(position(), expected_position)), 'Editor Back returned to a different board position'
                    driver.press(label='Back', role='button')
                    driver.wait(label='Next', role='button')
                except Exception:
                    # Keep only this disposable window's last semantic tree
                    # for diagnosis after the temporary profile is removed.
                    try:
                        (WORK / 'normal-entry-failure.json').write_text(json.dumps(driver.tree(), indent=2) + '\n')
                    except Exception:
                        pass
                    raise
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)
    proof = dict(binary=str(binary), binary_sha256=digest(binary), collection_sha256=receipt['sha256'],
                 verified='gameplay captures' if args.capture_only else
                     'proper artwork title -> Play -> map -> gameplay; legacy editor draft and moved game preserved across restart and named reinstall',
                 editor_identity='arcade.shovey-editor', consent_actions=consent_actions, captures=captures,
                 routing_verified=False)
    (WORK / 'capture-context.json').write_text(json.dumps(proof, indent=2) + '\n')
    if direct_error:
        raise AssertionError(direct_error)
    proof['routing_verified'] = not args.capture_only
    (WORK / 'capture-context.json').write_text(json.dumps(proof, indent=2) + '\n')
    if not args.capture_only:
        print('Shovey standalone and direct game entry: proper title -> Play -> map; legacy drafts, reinstall and saved-game continuity passed.')
    print('Real gameplay captures ready: ' + ('packaging/library' if args.capture_only else str(WORK / 'captures')))


if __name__ == '__main__':
    main()
