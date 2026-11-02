"""Remember a replayed level independently of progress; bound public map browsing.

Runs only against its own process on a private display, using disposable saves.
Artwork delivery is independently tested by world_map_journey_ui_test.py.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from world_map_test_support import private_environment
from shovey_standalone_ui_test import answer_cover_question, answer_level_updates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    parser.add_argument('--frontier', type=int, choices=(15, 74, 87, 99), default=99)
    args = parser.parse_args()
    frontier, public_last = args.frontier, args.frontier + 3
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    root = Path(__file__).resolve().parents[1]
    output = root / f'work/world-map-camera-test-{frontier}'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')

    @contextlib.contextmanager
    def application(profile, name):
        log_path = output / f'{name}.log'
        with log_path.open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()),
                stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                driver.wait(label='Play', role='button', timeout=60)
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                answer_level_updates(driver)
                if driver.find(label='How do you want to move?', role='text'):
                    driver.press(label='Swipe and tap')
                    driver.wait(label='Got it', role='button')
                if driver.find(label='Got it', role='button'):
                    driver.press(label='Got it')
                driver.wait(label='Levels', role='button', timeout=30)
                yield child
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)

    def resize(child, width, height):
        windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
        assert len(windows) == 1
        window = windows[0]
        assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
        subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
        subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            screen = driver.tree()[0]
            if (screen['width'], screen['height']) == (width, height):
                driver.wait_idle(frames=4)
                return window
            time.sleep(.05)
        raise AssertionError('Owned window did not resize')

    def selected(level):
        marker = driver.wait(key=33000 + level, role='button', visible=True)
        assert marker['selected'], marker
        return marker

    def public_nodes():
        nodes = driver.tree()
        ordinary = [node for node in nodes if node.get('kind') == 'button' and 33001 <= node.get('key', 0) <= 33175]
        assert all(node['key'] <= 33000 + public_last for node in ordinary), 'Beyond three locked previews'
        assert not any(node.get('key') in (34001, 34002, 34003) for node in nodes), 'Hidden secret leaked'
        assert not any(800000 <= node.get('key', 0) < 800100 for node in nodes), 'Mist seam overlay returned'
        return ordinary

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
        profile = Path(temporary)
        with application(profile, 'bootstrap'):
            driver.wait(contains='Level 1 / ', role='text')
        record = profile / 'games/arcade.shovey/records/local.campaign'
        text = record.read_text()
        header, marks = (6, 1000) if text.startswith('C5') else (4, 175)
        # Preserve the genuine untouched level-1 board and its fingerprint.
        # Earned progress is separate and includes level 1's completion mark.
        record.write_text(text[:2] + f'{frontier:0{header - 2}x}' + '1' * (frontier - 1) + '0' * (marks - frontier + 1) + text[header + marks:])
        with application(profile, 'remembered-one') as child:
            driver.wait(contains='Level 1 / ', role='text')
            for width, height in ((390, 844), (960, 600)):
                window = resize(child, width, height)
                driver.press(label='Levels', role='button')
                selected(1)
                public_nodes()
                driver.press(key=20022)
                driver.wait(contains='Level 1 / ', role='text')
                driver.press(label='Levels', role='button')
                first = selected(1)
                driver.key('d')
                driver.wait_idle(frames=3)
                sideways = driver.find(key=33001, role='button', visible=True)
                assert not sideways or sideways[0]['x'] < first['x'] - 20, 'Horizontal keyboard pan did not move'
                driver.key('home')
                selected(1)
                track = driver.wait(key=20108, visible=True)
                driver.drag((track['x'] + track['width'] * .25, track['y'] + track['height'] / 2),
                            (track['x'] + track['width'] * .7, track['y'] + track['height'] / 2))
                driver.wait_idle(frames=5)
                driver.key('home')
                first = selected(1)
                # A real content drag pans without changing the selected node.
                driver.drag((24, 220), (24, 460))
                driver.wait_idle(frames=8)
                moved = driver.find(key=33001, role='button', visible=True)
                assert not moved or moved[0]['y'] > first['y'] + 20, 'Content pan did not move'
                driver.key('home')
                selected(1)
                # Left/right choose the two arms of the explicit first fork.
                if public_last >= 19:
                    for _ in range(17):
                        driver.key('up')
                    selected(18)
                    driver.key('right')
                    selected(19)
                    driver.key('left')
                    selected(18)
                driver.key('end')
                last = selected(public_last)
                assert not last['enabled']
                public_nodes()
                driver.key('enter')
                driver.wait(label='Continue', role='button')
                # Extreme page input stops at the preview, not future levels.
                for _ in range(4):
                    driver.key('page_up')
                top = selected(public_last)
                assert abs(top['y'] - last['y']) < 1
                driver.drag((24, 220), (24, 460))
                driver.wait_idle(frames=8)
                assert abs(selected(public_last)['y'] - top['y']) < 1
                public_nodes()
                subprocess.run(['import', '-window', window, str(output / f'preview-{width}.png')], check=True)
                driver.key('home')
                first = selected(1)
                for _ in range(4):
                    driver.key('page_down')
                driver.key('home')
                selected(1)
                subprocess.run(['import', '-window', window, str(output / f'remembered-one-{width}.png')], check=True)
                # Select a completed replay, then reopen without frontier jumps.
                driver.press(key=33001, role='button')
                driver.wait(contains='Level 1 / ', role='text')
                driver.press(label='Levels', role='button')
                selected(1)
                driver.press(label='Continue', role='button')
                driver.wait(contains='Level 1 / ', role='text')
            # Resize an open selector, preserving the selected replay.
            driver.press(label='Levels', role='button')
            resize(child, 390, 844)
            selected(1)
            resize(child, 960, 600)
            selected(1)
            driver.press(key=20022)
        with application(profile, 'relaunch-one'):
            driver.wait(contains='Level 1 / ', role='text')
            driver.press(label='Levels', role='button')
            selected(1)
            public_nodes()
        if frontier == 99:
            with application(profile, 'selected-ninety-nine') as child:
                driver.press(label='Levels', role='button')
                driver.key('home')
                manifest = json.loads((root / 'assets/shovey/world-map/riverfold.json').read_text())
                edges = {(edge['from'], edge['to']) for edge in manifest['edges']}
                for current in range(1, 99):
                    driver.key('up' if (current, current + 1) in edges else 'right')
                driver.press(key=33099, role='button')
                driver.wait(contains='Level 99 / ', role='text')
                for width, height in ((390, 844), (960, 600)):
                    driver.press(label='Levels', role='button')
                    resize(child, width, height)
                    selected(99)
                    driver.press(key=20022)
                    driver.wait(contains='Level 99 / ', role='text')
            with application(profile, 'relaunch-ninety-nine'):
                driver.wait(contains='Level 99 / ', role='text')
                driver.press(label='Levels', role='button')
                selected(99)
        result = dict(remembered_level=1, reachable_level=frontier, public_last=public_last,
            viewports=[[390, 844], [960, 600]], reopen=True, resize=True, relaunch=True,
            pan=True, branch_navigation=True, hidden_secrets_absent=True)
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'Map camera local UI test passed: level 1 remembered, frontier {frontier}, preview {public_last}; reopen/resize/relaunch and private input')


if __name__ == '__main__':
    main()
