"""Walk every ordinary destination with the private hosted player's controls."""
import argparse
import collections
import contextlib
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from shovey_standalone_ui_test import answer_cover_question, answer_level_updates
from world_map_test_support import assert_fullscreen_map, private_environment, enter_classic_map

ROOT = Path(__file__).resolve().parents[1]


def table(source, name, parse):
    match = re.search(r'\b' + re.escape(name) + r':\s*\[\d+\]\w+\s*=\s*\.\[(.*?)\];', source, re.S)
    assert match, name
    text = re.sub(r'//[^\n]*', '', match.group(1))
    return [parse(value.strip()) for value in text.split(',') if value.strip()]


def actions(positions, edges):
    neighbors = collections.defaultdict(list)
    for a, b in edges:
        neighbors[a].append(b); neighbors[b].append(a)
    directions = [('left', -1, 0), ('up', 0, -1), ('down', 0, 1), ('right', 1, 0)]
    result = {}
    for node in range(1, 176):
        x, y = positions[node - 1]
        for key, kx, ky in directions:
            best, score = node, 0.0
            for other in neighbors[node]:
                dx = positions[other - 1][0] - x; dy = positions[other - 1][1] - y
                distance = math.hypot(dx, dy)
                candidate = (dx * kx + dy * ky) / distance if distance else 0
                if candidate > score:
                    best, score = other, candidate
            result[node, key] = best
    return result


def path(action, start, target):
    queue = collections.deque([start]); previous = {start: None}
    while queue and target not in previous:
        current = queue.popleft()
        for key in ('left', 'up', 'down', 'right'):
            nxt = action[current, key]
            if nxt not in previous:
                previous[nxt] = current, key; queue.append(nxt)
    assert target in previous, ('destination unreachable by directional controls', start, target)
    steps = []
    while target != start:
        before, key = previous[target]; steps.append((key, target)); target = before
    return reversed(steps)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    output = ROOT / 'work/world-map-all-destinations-test'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')
    source = (ROOT / 'src/world_map_layout.zi').read_text()
    graph = (ROOT / 'src/world_map_progression.zi').read_text()
    flat = table(graph, 'world_map_edges', int)
    edges = list(zip(flat[::2], flat[1::2])); assert len(edges) == 178
    coordinates = []
    for name in ('world_map_positions', 'world_map_landscape_positions'):
        flat = table(source, name, float); assert len(flat) == 350
        coordinates.append(list(zip(flat[::2], flat[1::2])))

    @contextlib.contextmanager
    def app(profile, name):
        logfile = output / f'{name}.log'
        with logfile.open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, logfile)
            try:
                answer_cover_question(driver); driver.press(label='Play', role='button')
                enter_classic_map(driver)
                yield child
            finally:
                if child.poll() is None: child.terminate()
                child.wait(timeout=10)

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as tmp:
        profile = Path(tmp)
        with app(profile, 'bootstrap'):
            driver.press(key=20122, role='button'); answer_level_updates(driver)
            driver.wait(contains='Level 1 / ', role='text', timeout=30)
        save = profile / 'games/arcade.shovey/records/local.campaign'; text = save.read_text()
        assert text.startswith('C6')
        save.write_text('C600af' + '1' * 174 + '0' * 826 + text[1006:])
        for orientation, (width, height) in enumerate(((390, 844), (960, 600))):
            action = actions(coordinates[orientation], edges)
            with app(profile, f'journey-{width}') as child:
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
                driver.wait_idle(frames=4); driver.key('home')
                current = 1; seen = {1}
                for target in range(2, 176):
                    for key, expected in path(action, current, target):
                        driver.key(key)
                        marker = driver.wait(key=33000 + expected, role='button', visible=True)
                        assert marker['selected'] and marker['enabled'], (width, key, current, expected, marker)
                        assert marker['width'] >= 56 and marker['height'] >= 56, marker
                        current = expected
                    seen.add(current)
                    if target in (15, 81, 118, 146, 175):
                        driver.wait_idle(frames=8)
                        subprocess.run(['import', '-window', window, str(output / f'continuous-{width}-level-{target}.png')],check=True)
                assert seen == set(range(1, 176)), (width, len(seen))
                driver.key('home'); assert driver.wait(key=33001, role='button')['selected']
                assert driver.wait(label='Level 1', role='text')
    print('Private map journey local test passed: all 175 destinations selectable by directional controls in both orientations')


if __name__ == '__main__':
    main()
