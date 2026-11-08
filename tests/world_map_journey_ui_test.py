"""Verify real whole-scene coverage and rail joins in a private hosted player.

All required art/geometry comes from tracked files. Captures include both fork
arms at the garden/forest join and every other transition in both compositions.
"""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from PIL import Image
from world_map_art_test import inventory
from world_map_all_destinations_ui_test import table, actions, path
from world_map_test_support import private_environment, assert_fullscreen_map, digest, enter_classic_map
from shovey_standalone_ui_test import answer_cover_question, answer_level_updates

ROOT = Path(__file__).resolve().parents[1]


def area_covered(rects, width, height):
    rectangles = [(max(0, r[0]), max(0, r[1]), min(width, r[0] + r[2]), min(height, r[1] + r[3])) for r in rects]
    xs = sorted({0, width, *(r[0] for r in rectangles), *(r[2] for r in rectangles)})
    total = 0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((r[1], r[3]) for r in rectangles if r[0] <= left and r[2] >= right and r[3] > r[1])
        end = 0; covered = 0
        for top, bottom in spans:
            if bottom > end: covered += bottom - max(top, end); end = bottom
        total += (right - left) * covered
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    parser.add_argument('--secrets-only', action='store_true')
    parser.add_argument('--landscape-beach-only', action='store_true')
    parser.add_argument('--large-portrait-only', action='store_true')
    args = parser.parse_args()
    manifest = inventory()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    output = ROOT / ('work/world-map-journey-landscape-beach-test' if args.landscape_beach_only else ('work/world-map-journey-large-portrait-test' if args.large_portrait_only else 'work/world-map-journey-test'))
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')
    layout = (ROOT / 'src/world_map_layout.zi').read_text()
    graph = (ROOT / 'src/world_map_progression.zi').read_text()
    flat = table(graph, 'world_map_edges', int); edges = list(zip(flat[::2], flat[1::2]))
    assert len(edges) == 178
    zoom = float(re.search(r'WorldMapWorldZoom\s*::\s*([\d.]+)', layout)[1])
    count = int(re.search(r'WorldMapRailSampleCount\s*::\s*(\d+)', layout)[1])
    coordinates = []
    for name in ('world_map_positions', 'world_map_landscape_positions'):
        values = table(layout, name, float); coordinates.append(list(zip(values[::2], values[1::2])))
    assignments = {}
    for orientation, points in zip(('portrait', 'landscape'), coordinates):
        assignments[orientation] = []
        for x, y in points:
            found = [s['index'] for s in manifest['scenes']
                if (lambda r: r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3])(s[orientation]['world_bounds_before_zoom'])]
            assert 1 <= len(found) <= 2, (orientation, x, y, found)
            assignments[orientation].append(found[-1])
    peak_kib = 0; captures = []; seen_assets = set(); minimum_gap = float('inf'); movements = []

    @contextlib.contextmanager
    def app(profile, name):
        logfile = output / (name + '.log')
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

    def inspect(child, width, height):
        nonlocal peak_kib, minimum_gap
        for line in Path(f'/proc/{child.pid}/status').read_text().splitlines():
            if line.startswith('VmHWM:'): peak_kib = max(peak_kib, int(line.split()[1])); break
        nodes = driver.tree()
        images = [n for n in nodes if n.get('kind') == 'image' and n.get('visible') and n.get('detail', '').endswith('.webp')]
        seen_assets.update(Path(n['detail']).name for n in images)
        rects = [(n['x'], n['y'], n['width'], n['height']) for n in images]
        missing = width * height - area_covered(rects, width, height)
        assert missing <= max(width, height) * 1.1, ('unpainted viewport area', missing, width, height)
        buttons = [n for n in nodes if 33001 <= n.get('key', 0) <= 33175 and n.get('visible')]
        for i, a in enumerate(buttons):
            assert a['width'] == 56 and a['height'] == 56
            for b in buttons[i + 1:]:
                distance = math.hypot(a['x'] - b['x'], a['y'] - b['y'])
                minimum_gap = min(minimum_gap, distance - 52)
                assert distance >= 79, ('buttons crowded', a, b, distance)
        return nodes

    def capture(child, window, width, height, name):
        driver.wait_idle(frames=5); inspect(child, width, height)
        target = output / (name + '.png')
        subprocess.run(['import', '-window', window, str(target)], check=True)
        with Image.open(target) as im:
            image = im.convert('RGB')
            # The retained fallback fill is a flat exact color. A former gap
            # exposed tens of thousands of these pixels; artwork has texture.
            flat = sum(pixel == (97, 157, 65) for pixel in image.getdata())
            assert flat < width * height * .001, ('placeholder fill exposed', name, flat)
        captures.append(target.name)

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as tmp:
        profile = Path(tmp)
        with app(profile, 'bootstrap'):
            driver.press(key=20122, role='button'); answer_level_updates(driver)
            driver.wait(contains='Level 1 / ', role='text', timeout=30)
            if driver.find(label='How do you want to move?', role='text'):
                driver.press(label='Swipe and tap', role='button');driver.wait(label='Got it', role='button')
            if driver.find(label='Got it', role='button'):driver.press(label='Got it', role='button')
        records = profile / 'games/arcade.shovey/records';save = records / 'local.campaign';text = save.read_text()
        assert text.startswith('C6')
        save.write_text('C600af' + '1' * 174 + '0' * 826 + text[1006:])
        if args.secrets_only:
            for key in ('29a', '175a', '175b'): (records / ('local.secret' + key)).write_text('1')
        views = [('portrait', (600, 1100), coordinates[0])] if args.large_portrait_only else list(zip(('portrait', 'landscape'), ((390, 844), (960, 600)), coordinates))
        if args.landscape_beach_only: views = [('landscape', (960, 600), coordinates[1])]
        for orientation, (width, height), points in views:
            action = actions(points, edges)
            with app(profile, 'journey-' + orientation) as child:
                windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
                assert len(windows) == 1;window = windows[0]
                assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
                subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True)
                for _ in range(100):
                    screen = driver.tree()[0]
                    if (screen['width'], screen['height']) == (width, height): break
                    time.sleep(.05)
                else: raise AssertionError('Private window did not resize')
                current = 1
                def reveal(target):
                    nonlocal current
                    for key, expected in path(action, current, target):
                        driver.key(key); current = expected
                        marker = driver.wait(key=33000 + current, role='button', visible=True)
                        assert marker['selected'] and marker['enabled'], marker
                    driver.wait_idle(frames=2)
                if args.secrets_only:
                    for anchor, identity, label in ((29, 1003, '21-S'), (175, 1001, '159-S1'), (175, 1002, '159-S2')):
                        driver.key('home');current = 1;reveal(anchor)
                        room = driver.wait(key=33000 + identity, role='button', visible=True)
                        assert room['enabled'] and room['label'] == label, room
                        assert room['visible_width'] == room['visible_height'] == 56, room
                        x, y = driver.center(room)
                        driver.pointer(x, y, down=True);driver.pointer(x, y, down=False);driver.release_pointer()
                        capture(child, window, width, height, f'{orientation}-secret-{identity}')
                        driver.press(key=20122, role='button')
                        driver.wait(contains='Level ' + label, role='text', timeout=30)
                        driver.press(label='Back', role='button');assert_fullscreen_map(driver)
                else:
                    visited = {1}
                    for target in range(143 if args.landscape_beach_only else 2, 176):
                        reveal(target);visited.add(current);inspect(child, width, height)
                        if orientation == 'portrait' and target == 63:
                            capture(child, window, width, height, 'portrait-cave-fork')
                        if orientation == 'landscape' and target in (18, 19, 24, 28, 63, 64, 71, 73, 143, 175):
                            capture(child, window, width, height, f'landscape-{target}')
                    assert visited == ({1, *range(143, 176)} if args.landscape_beach_only else set(range(1, 176)))
                    capture(child, window, width, height, orientation + '-beach-end')
                    # The whole accepted boat and the dock's final circle
                    # must be inside the actual public viewport above Play.
                    image = driver.wait(key=60001 + manifest['scenes'][-1]['index'], visible=True)
                    terminal = manifest['scenes'][-1][orientation]
                    feature = manifest['terminal_features'][orientation]
                    sx = image['width'] / terminal['size'][0]
                    sy = image['height'] / terminal['size'][1]
                    bx, by, bw, bh = feature['boat']
                    if orientation == 'landscape': bx -= terminal['crop_travel'][0]
                    rectangle = [image['x'] + bx * sx, image['y'] + by * sy, bw * sx, bh * sy]
                    panel_top = driver.wait(key=20121, role='text')['y'] - 8
                    assert rectangle[0] >= -1 and rectangle[1] >= -1, ('boat start cropped', orientation, rectangle)
                    assert rectangle[0] + rectangle[2] <= width + 1 and rectangle[1] + rectangle[3] <= panel_top + 1, ('boat sail or hull cropped', orientation, rectangle, panel_top)
                    final = driver.wait(key=33175, role='button', visible=True)
                    assert final['selected'] and final['visible_width'] == final['visible_height'] == 56
                    movements.append({'orientation': orientation, 'whole_boat': rectangle, 'level': 175, 'panel_top': panel_top})
                    # Visit every actual shared source band. The asset test
                    # proves every native pixel; here both runtime images must
                    # overlap on-screen and paint the full app viewport.
                    for join in manifest['joins'][orientation]:
                        if args.landscape_beach_only and join['from'] < 13: continue
                        axis = 0 if orientation == 'landscape' else 1
                        travel = join['travel_start'] + join['shared_native_rows'] / 2
                        full = manifest['world_bounds_before_zoom'][orientation]
                        coordinate = travel if axis == 0 else full[3] - 1 - travel
                        closest = min(range(1,176), key=lambda n: abs(points[n-1][axis] - coordinate))
                        reveal(closest)
                        first = driver.wait(key=60001 + join['from'], visible=True)
                        second = driver.wait(key=60001 + join['to'], visible=True)
                        low = max(first['x' if axis == 0 else 'y'], second['x' if axis == 0 else 'y'])
                        high = min(first['x' if axis == 0 else 'y'] + first['width' if axis == 0 else 'height'], second['x' if axis == 0 else 'y'] + second['width' if axis == 0 else 'height'])
                        assert high > low and high > 0 and low < (width if axis == 0 else height - 112), ('shared band not actually visible', orientation, join, first, second)
                        capture(child, window, width, height, f"join-{width}-{join['from']:02}")
                        movements.append({'orientation': orientation, 'join': [join['from'], join['to']], 'selected': closest, 'shared_screen_interval': [low,high]})
                    expected = {Path(s[orientation]['path']).name for s in manifest['scenes']}
                    if args.landscape_beach_only: expected = {Path(s[orientation]['path']).name for s in manifest['scenes'][13:]}
                    assert expected <= seen_assets, ('missing actual painted assets', expected - seen_assets)
    result = {'levels_per_orientation': 33 if args.landscape_beach_only else 175, 'orientations': ['landscape'] if args.landscape_beach_only else ['portrait', 'landscape'], 'captures': captures,
        'painted_assets_seen': sorted(seen_assets), 'peak_rss_kib': peak_kib, 'minimum_visual_gap_px': minimum_gap,
        'game_bytes': (args.binary.parent.parent / 'games/shovey.zx').stat().st_size if (args.binary.parent.parent / 'games/shovey.zx').exists() else None,
        'provenance': {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / 'src/world_map_layout.zi', ROOT / 'src/world_map_view.zi', ROOT / 'assets/shovey/world-map/scenes.json')},
        'wheel_camera_movements': movements, 'binary_sha256': digest(args.binary)}
    (output / ('secrets-result.json' if args.secrets_only else 'result.json')).write_text(json.dumps(result, indent=2) + '\n')
    if args.secrets_only:print('Discovered-secret local UI test passed: all 3 stable rooms selected by real pointer and opened with Play in both orientations')
    elif args.landscape_beach_only:print(f'Landscape whole-beach local UI test passed: 33 destinations, actual painted coverage, authored movement and reverse; {len(captures)} real captures; peak RSS {peak_kib / 1024:.1f}MiB')
    else:print(f'Whole-map journey local UI test passed: 175 destinations per orientation, actual painted coverage, all native shared bands and whole boat/dock framing; {len(captures)} real captures; peak RSS {peak_kib / 1024:.1f}MiB')


if __name__ == '__main__':
    main()
