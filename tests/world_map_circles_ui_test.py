"""Verify map circle geometry, names and detached discovery in a private host."""
import argparse
import contextlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from world_map_all_destinations_ui_test import table, actions, path
from world_map_test_support import private_environment, assert_fullscreen_map, digest
from shovey_standalone_ui_test import answer_cover_question, answer_level_updates

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    args = parser.parse_args()
    output = ROOT / 'work/map-circle-results'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')
    flat = table((ROOT / 'src/world_map_progression.zi').read_text(), 'world_map_edges', int)
    edges = list(zip(flat[::2], flat[1::2]))

    @contextlib.contextmanager
    def app(profile, name):
        logfile = output / (name + '.log')
        with logfile.open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, logfile)
            try:
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                assert_fullscreen_map(driver)
                yield child
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as tmp:
        profile = Path(tmp)
        with app(profile, 'bootstrap'):
            assert not any(34001 <= n.get('key', 0) <= 34003 for n in driver.tree())
            driver.press(key=20122, role='button'); answer_level_updates(driver)
            driver.wait(contains='Level 1 / ', role='text')
        records = profile / 'games/arcade.shovey/records'
        save = records / 'local.campaign'; text = save.read_text()
        assert text.startswith('C6')
        save.write_text('C600af' + '1' * 174 + '0' * 826 + text[1006:])
        (records / 'local.secret175a').write_text('1')
        (records / 'local.secret175b').write_text('1')
        for width, height, name in ((390, 844, 'portrait'), (960, 600, 'landscape')):
            flat = table((ROOT / 'src/world_map_layout.zi').read_text(),
                'world_map_positions' if width == 390 else 'world_map_landscape_positions', float)
            action = actions(list(zip(flat[::2], flat[1::2])), edges)
            with app(profile, name) as child:
                windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
                assert len(windows) == 1
                window = windows[0]
                assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
                for _ in range(100):
                    screen = driver.tree()[0]
                    if (screen['width'], screen['height']) == (width, height): break
                    time.sleep(.05)
                else: raise AssertionError('Private window did not resize')
                driver.wait_idle(frames=4)
                current = 1
                for target, label in ((19, '19-A1'), (24, '19-B1'), (175, '159')):
                    for key, expected in path(action, current, target):
                        driver.key(key); current = expected
                    driver.wait(label='Level ' + label, role='text')
                    nodes = [n for n in driver.tree() if 33001 <= n.get('key', 0) <= 34003 and n.get('visible')]
                    for n in nodes:
                        assert n['width'] == 56 and n['height'] == 56, n
                    for i, a in enumerate(nodes):
                        for b in nodes[i + 1:]:
                            assert math.hypot(a['x'] - b['x'], a['y'] - b['y']) >= 56, (a, b)
                    subprocess.run(['import', '-window', window, str(output / f'{name}-{label}.png')], check=True)
                sibling = driver.wait(key=34002, role='button', visible=True)
                assert sibling['visible_width'] == 56 and sibling['visible_height'] == 56, sibling
                room = driver.wait(key=34001, role='button', visible=True)
                assert room['enabled'] and room['label'] == '159-S1', room
                assert room['visible_width'] == 56 and room['visible_height'] == 56, room
                assert not driver.find(key=34003, role='button'), 'Undiscovered secret exposed'
                # Rectangle corners lie outside this circular target. Actual
                # pointer routing must leave the selected ordinary node alone.
                driver.pointer(room['x'] + 1, room['y'] + 1, down=True)
                driver.pointer(room['x'] + 1, room['y'] + 1, down=False)
                driver.release_pointer()
                assert driver.wait(key=33175, role='button')['selected']
                # Real pointer selection followed by explicit Play opens the secret.
                x, y = driver.center(room)
                driver.pointer(x, y, down=True); driver.pointer(x, y, down=False); driver.release_pointer()
                driver.wait(label='Level 159-S1', role='text')
                subprocess.run(['import', '-window', window, str(output / f'{name}-secret.png')], check=True)
                driver.press(key=20122, role='button')
                driver.wait(contains='Level 159-S1', role='text')
    (output / 'ui-result.json').write_text(json.dumps({'orientations': ['portrait', 'landscape'],
        'names': ['19-A1', '19-B1', '159-S1'], 'target_diameter': 56,
        'secret_pointer_select_and_play': True, 'undiscovered_hidden': True,
        'binary_sha256': digest(args.binary), 'view_sha256': digest(ROOT / 'src/world_map_view.zi'),
        'art_sha256': digest(ROOT / 'src/world_map_art.zi')}, indent=2) + '\n')
    print('Map circles local UI test passed: both orientations, 56px disjoint circles, branch names, discovered secret pointer selection and Play')


if __name__ == '__main__':
    main()
