"""Exercise the actual map camera and selection in a private player/profile."""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from world_map_test_support import private_environment, assert_fullscreen_map, enter_classic_map
from shovey_standalone_ui_test import answer_cover_question, answer_level_updates


def native_scale(width, height):
    """Screen pixels per authored v5 painting unit, as WorldMapViewNativeScale."""
    if width < height:
        return max(.41, width / 1086)
    return height / 941


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    parser.add_argument('--frontier', type=int, default=99)
    parser.add_argument('--forks-only', action='store_true')
    parser.add_argument('--journey', action='store_true')
    parser.add_argument('--zoom-settle', action='store_true')
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    root = Path(__file__).resolve().parents[1]
    output = root / ('work/map-geometry-private-finish/ui-zoom-settle' if args.zoom_settle else
                     ('work/map-geometry-private-finish/ui-journey' if args.journey else
                     ('work/map-fork-refinement/ui' if args.forks_only else 'work/world-map-camera-test-99'))
                     )
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')
    journey_proof = []
    reach_proof = []
    settle_proof = []

    @contextlib.contextmanager
    def app(profile, name):
        log_path = output / f'{name}.log'
        with log_path.open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                enter_classic_map(driver)
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
        for _ in range(100):
            screen = driver.tree()[0]
            if (screen['width'], screen['height']) == (width, height):
                driver.wait_idle(frames=4)
                return window
            time.sleep(.05)
        raise AssertionError('Private player did not resize')

    def painting():
        """The map viewport and the union of its visible painting tiles."""
        view = driver.wait(key=20105, visible=True)
        tiles = [n for n in driver.tree() if n.get('visible') and 60001 <= n.get('key', 0) <= 60037]
        assert tiles, 'no painting drawn'
        return view, (min(n['x'] for n in tiles), min(n['y'] for n in tiles),
                      max(n['x'] + n['width'] for n in tiles), max(n['y'] + n['height'] for n in tiles))

    def reach_ends(width, height, label):
        """Home shows the start; the wheel reaches both painting edges at any
        progress. Portrait shows the painting's foot. Landscape centres level 1
        on its road, the painted left extension fills the screen beside it, and
        scrolling back pans on past level 1 to the painting's left edge."""
        portrait = width < height
        driver.key('home')
        selected(1)
        driver.wait_idle(frames=5)
        home = driver.wait(key=33001, role='button', visible=True)
        view, (left, top, right, bottom) = painting()
        if portrait:
            assert bottom <= view['y'] + view['height'] + 1, ('start edge not reached', label, width, bottom, view)
        else:
            assert left <= view['x'] + 1, ('blank ground left of the start', label, width, left, view)
            for batch in range(20):
                subprocess.run(['xdotool', 'mousemove', str(width // 2), str(height // 3),
                                'click', '--repeat', '10', '--delay', '8', '5'], check=True)
                driver.wait_idle(frames=3)
                view, (left, top, right, bottom) = painting()
                if left >= view['x'] - 1:
                    break
            assert left >= view['x'] - 1, ('start edge not reached', label, width, left, view)
            assert left <= view['x'] + 1, ('scrolled past the start edge', label, width, left, view)
            assert driver.wait(label='Level 1', role='text'), 'Browsing changed the selected board'
            # Home centres level 1 again, exactly where it began.
            driver.key('home')
            selected(1)
            driver.wait_idle(frames=5)
            again = driver.wait(key=33001, role='button', visible=True)
            assert abs(again['x'] - home['x']) <= 1 and abs(again['y'] - home['y']) <= 1, ('Home did not recentre level 1', home, again)
            reach_proof.append({'progress': label, 'viewport': [width, height], 'start_batches': batch + 1})
        reached = False
        for batch in range(40):
            subprocess.run(['xdotool', 'mousemove', str(width // 2), str(height // 3),
                            'click', '--repeat', '20', '--delay', '8', '4'], check=True)
            driver.wait_idle(frames=3)
            view, (left, top, right, bottom) = painting()
            if (top >= view['y'] - 1) if portrait else (right <= view['x'] + view['width'] + 1):
                reached = True
                break
        assert reached, ('far edge of the painting unreachable', label, width, (left, top, right, bottom), view)
        # The map end shows locked boards locked and the selection unchanged.
        assert driver.wait(label='Level 1', role='text'), 'Browsing changed the selected board'
        end = driver.find(key=33175, role='button', visible=True)
        assert end, ('the last board is not drawn at the map end', label, width)
        if label == 'fresh':
            assert not end[0]['enabled'], 'A locked board became playable'
        assert not driver.find(key=34001) and not driver.find(key=34002) and not driver.find(key=34003), \
            ('an unfound room was drawn', label, width)
        reach_proof.append({'progress': label, 'viewport': [width, height], 'batches': batch + 1})
        driver.key('home')
        selected(1)

    def selected(level):
        marker = driver.wait(key=33000 + level, role='button', visible=True)
        assert marker['selected'], marker
        if args.journey or args.zoom_settle:
            # Read the actual public panel origin, including host insets and
            # localized caption layout. The avatar extends 20px above the hit.
            panel_top = driver.wait(key=20121, role='text')['y'] - 8
            assert marker['y'] >= 20 and marker['y'] + marker['height'] <= panel_top, ('selected board or avatar hidden by Play panel', level, marker, panel_top)
        return marker

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as tmp:
        profile = Path(tmp)
        with app(profile, 'bootstrap') as child:
            if not (args.journey or args.zoom_settle or args.forks_only):
                for width, height in ((390, 844), (960, 600)):
                    resize(child, width, height)
                    reach_ends(width, height, 'fresh')
            selected(1)
            driver.press(key=20122, role='button')
            answer_level_updates(driver)
            driver.wait(contains='Level 1 / ', role='text', timeout=30)
            if driver.find(label='How do you want to move?', role='text'):
                driver.press(label='Swipe and tap', role='button')
                driver.wait(label='Got it', role='button')
            if driver.find(label='Got it', role='button'):
                driver.press(label='Got it', role='button')
        record = profile / 'games/arcade.shovey/records/local.campaign'
        saved = record.read_text()
        assert saved.startswith('C6')
        record.write_text('C6' + f'{args.frontier:04x}' + '1' * (args.frontier - 1) +
                          '0' * (1001 - args.frontier) + saved[1006:])
        with app(profile, 'replay') as child:
            for width, height in ((390, 844), (960, 600)):
                window = resize(child, width, height)
                assert_fullscreen_map(driver)
                if args.zoom_settle:
                    assert args.frontier == 175
                    from world_map_all_destinations_ui_test import table, actions, path
                    layout = (root / 'src/world_map_layout.zi').read_text()
                    graph = (root / 'src/world_map_progression.zi').read_text()
                    flat = table(graph, 'world_map_edges', int)
                    edges = list(zip(flat[::2], flat[1::2]))
                    values = table(layout, 'world_map_positions' if width < height else 'world_map_landscape_positions', float)
                    positions = list(zip(values[::2], values[1::2]))
                    action = actions(positions, edges)

                    def rendered_scale():
                        buttons = [n for n in driver.tree() if n.get('visible') and 33001 <= n.get('key', 0) <= 33175]
                        assert len(buttons) >= 2
                        a, b = buttons[:2]
                        return math.hypot(a['x'] - b['x'], a['y'] - b['y']) / math.dist(positions[a['key'] - 33001], positions[b['key'] - 33001])

                    # Choose a second genuine zoom transition from the new
                    # native geometry rather than an old painting's IDs. The
                    # actual rendered scale must still change and settle.
                    baseline = native_scale(width, height)
                    def expected_scale(at):
                        if at <= 7: return baseline
                        ax, ay = positions[at - 1]
                        nearby = [p for p in positions if abs(p[0] - ax) <= (width + 128) / baseline and abs(p[1] - ay) <= (height + 128) / baseline]
                        gap = min(math.dist(a,b) for i,a in enumerate(nearby) for b in nearby[i+1:])
                        return min(1.3,max(baseline,80.1/gap))
                    candidates = [(a,b) for a,b in edges if a >= 8 and abs(expected_scale(a)-expected_scale(b)) > .015]
                    if not candidates:
                        # v5 keeps one native scale; nothing may settle to another.
                        driver.key('home')
                        selected(1)
                        driver.wait_idle(frames=5)
                        assert abs(rendered_scale() - baseline) < .01, ('v5 scale differs from native', width, rendered_scale(), baseline)
                        settle_proof.append({'viewport': [width, height], 'native_scale': baseline})
                        continue
                    paired_transition = max(candidates,key=lambda edge: abs(expected_scale(edge[0])-expected_scale(edge[1])))
                    for previous, target in ((7, 8), paired_transition):
                        driver.key('home')
                        for key, destination in path(action, 1, previous):
                            driver.key(key)
                            selected(destination)
                        driver.wait_idle(frames=8)
                        old_scale = rendered_scale()
                        for key, destination in path(action, previous, target):
                            driver.key(key)
                            selected(destination)
                        # No wheel/drag/reveal follows the transition. The next
                        # idle frames must apply the zoom's final framing.
                        driver.wait_idle(frames=8)
                        settled = selected(target)
                        new_scale = rendered_scale()
                        assert abs(new_scale - old_scale) > .005, ('scenario did not change zoom', width, previous, target, old_scale, new_scale)
                        panel_top = driver.wait(key=20121, role='text')['y'] - 8
                        avatar = driver.wait(key=64999, visible=True)
                        assert avatar['y'] >= 0 and avatar['y'] + avatar['height'] <= panel_top, ('settled avatar occluded', avatar, panel_top)
                        # Explicitly selecting that same endpoint is an
                        # independent camera entry path with identical policy.
                        driver.press(key=33000 + target, role='button')
                        driver.wait_idle(frames=8)
                        revealed = selected(target)
                        assert abs(settled['x'] - revealed['x']) <= 1 and abs(settled['y'] - revealed['y']) <= 1, ('idle zoom framing differed from reveal', width, target, settled, revealed)
                        settle_proof.append({'viewport':[width,height], 'from':previous, 'selected':target,
                            'old_scale':old_scale,'settled_scale':new_scale,
                            'settled_xy':[settled['x'],settled['y']], 'revealed_xy':[revealed['x'],revealed['y']]})
                        subprocess.run(['import','-window',window,str(output / f'settled-{width}-{target}.png')],check=True)
                    driver.key('home')
                    selected(1)
                    continue
                if args.journey:
                    assert args.frontier == 175
                    from world_map_all_destinations_ui_test import table, actions, path
                    from world_map_journey_ui_test import area_covered
                    layout = (root / 'src/world_map_layout.zi').read_text()
                    graph = (root / 'src/world_map_progression.zi').read_text()
                    flat = table(graph, 'world_map_edges', int)
                    edges = list(zip(flat[::2], flat[1::2]))
                    values = table(layout, 'world_map_positions' if width < height else 'world_map_landscape_positions', float)
                    positions = list(zip(values[::2], values[1::2]))
                    action = actions(positions, edges)

                    def inspect():
                        nodes = driver.tree()
                        buttons = [n for n in nodes if n.get('visible') and 33001 <= n.get('key', 0) <= 33175]
                        minimum = float('inf')
                        for index, a in enumerate(buttons):
                            assert a['width'] == a['height'] == 56, a
                            for b in buttons[index + 1:]:
                                distance = math.hypot(a['x'] - b['x'], a['y'] - b['y'])
                                minimum = min(minimum, distance)
                                assert distance >= 79.0, ('crowded camera region', width, a, b, distance)
                        images = [n for n in nodes if n.get('visible') and n.get('kind') == 'image' and n.get('detail', '').endswith('.webp')]
                        rects = [(n['x'], n['y'], n['width'], n['height']) for n in images]
                        missing = width * height - area_covered(rects, width, height)
                        assert missing <= max(width, height) * 1.1, ('unpainted map', width, missing)
                        scale = None
                        if len(buttons) >= 2:
                            a, b = buttons[:2]
                            source_distance = math.dist(positions[a['key'] - 33001], positions[b['key'] - 33001])
                            scale = math.hypot(a['x'] - b['x'], a['y'] - b['y']) / source_distance
                        return {'minimum_center_distance': minimum if math.isfinite(minimum) else None,
                                'screen_per_authored_unit': scale}, buttons

                    driver.key('home')
                    current = 1
                    for target in range(2, 176):
                        for key, destination in path(action, current, target):
                            driver.key(key)
                            selected(destination)
                            current = destination
                        driver.wait_idle(frames=3)
                        proof, _ = inspect()
                        proof.update(viewport=[width, height], selected=current)
                        journey_proof.append(proof)
                        forks = table(graph, 'world_map_forks', int)
                        for entry, left, right, merge in zip(forks[::5], forks[1::5], forks[2::5], forks[3::5]):
                            if not entry < current < merge: continue
                            others = range(right, merge) if current < right else range(left, right)
                            axis = 1 if width < height else 0
                            counterpart = min(others, key=lambda p: abs(positions[p-1][axis] - positions[current-1][axis]))
                            partner = driver.wait(key=33000 + counterpart, role='button', visible=True)
                            assert 0 <= partner['x'] <= width - 56 and 0 <= partner['y'] <= height - 112 - 56, ('opposite arm clipped',width,current,counterpart,partner)
                        if target == 77:
                            baseline = native_scale(width, height)
                            assert abs(proof['screen_per_authored_unit'] - baseline) < .01, proof
                        if target in (10, 20, 29, 49, 77, 81, 97, 113, 118, 141, 146, 175):
                            subprocess.run(['import', '-window', window, str(output / f'journey-{width}-{target}.png')], check=True)

                    # Selection stays at a spacious road while wheel browsing
                    # reaches a denser painting. Framing must track the camera.
                    driver.key('home')
                    for key, destination in path(action, 1, 20):
                        driver.key(key)
                        selected(destination)
                    driver.wait_idle(frames=5)
                    panel = driver.wait(key=20121, role='text')['label']
                    saw_dense = False
                    for step in range(180):
                        subprocess.run(['xdotool', 'mousemove', '20', str(height // 2), 'click', '4'], check=True)
                        driver.wait_idle(frames=3)
                        proof, buttons = inspect()
                        assert driver.wait(key=20121, role='text')['label'] == panel, 'Wheel changed selected board'
                        ids = {node['key'] - 33000 for node in buttons}
                        if 97 in ids and 98 in ids:
                            assert proof['screen_per_authored_unit'] >= native_scale(width, height) - .01, proof
                            proof.update(viewport=[width, height], selected=20, wheel_region=[97, 98])
                            journey_proof.append(proof)
                            subprocess.run(['import', '-window', window, str(output / f'fixed-selection-{width}-97.png')], check=True)
                            saw_dense = True
                            break
                    assert saw_dense, ('Wheel did not reach dense region on the chosen arm', width)
                    driver.key('home')
                    selected(1)
                    continue
                if args.forks_only:
                    from world_map_all_destinations_ui_test import table, actions, path
                    layout = (root / 'src/world_map_layout.zi').read_text()
                    graph = (root / 'src/world_map_progression.zi').read_text()
                    flat = table(graph, 'world_map_edges', int)
                    edges = list(zip(flat[::2], flat[1::2]))
                    values = table(layout, 'world_map_positions' if width < height else 'world_map_landscape_positions', float)
                    positions = list(zip(values[::2], values[1::2]))
                    action = actions(positions, edges)
                    forks = table(graph, 'world_map_forks', int)
                    observations = []
                    for entry, left, right in zip(forks[::5], forks[1::5], forks[2::5]):
                        driver.key('home')
                        for key, destination in path(action, 1, entry):
                            driver.key(key)
                            selected(destination)
                        driver.wait_idle(frames=5)
                        start = selected(entry)
                        for place in (left, right):
                            choice = driver.wait(key=33000 + place, role='button', visible=True)
                            assert choice['width'] == choice['height'] == 56
                            assert 0 <= choice['x'] <= width - 56 and 0 <= choice['y'] <= height - 112 - 56, ('fork option clipped or behind Play',width,entry,choice)
                        subprocess.run(['import', '-window', window, str(output / f'fork-{width}-{entry}.png')], check=True)
                        endpoints = []
                        for side, px in [('left', 20), ('right', width - 20)]:
                            # A selection explicitly resets the wheel to the fork.
                            driver.press(key=33000 + entry, role='button')
                            driver.wait_idle(frames=5)
                            before = selected(entry)
                            driver.release_pointer()
                            subprocess.run(['xdotool', 'mousemove', str(px), str(height // 2), 'click', '4'], check=True)
                            driver.wait_idle(frames=5)
                            after = driver.wait(key=33000 + entry, role='button')
                            assert after['selected'] and driver.find(key=20105,visible=True), 'Wheel changed selection or opened a board'
                            endpoints.append((after['x'],after['y']))
                            subprocess.run(['import', '-window', window, str(output / f'wheel-{width}-{entry}-{side}.png')], check=True)
                            # Reverse with the cursor on the opposite side: no arm switch.
                            subprocess.run(['xdotool', 'mousemove', str(width - px), str(height // 2), 'click', '5'], check=True)
                            driver.wait_idle(frames=5)
                            restored = selected(entry)
                            assert abs(restored['x'] - before['x']) <= 2 and abs(restored['y'] - before['y']) <= 2, ('reverse changed road',width,entry,side,before,restored)
                        assert math.dist(*endpoints) > 8, ('cursor halves followed same arm',width,entry,endpoints)
                        observations.append({'entry':entry,'endpoints':endpoints})
                    (output / f'forks-{width}.json').write_text(json.dumps(observations,indent=2)+'\n')
                    driver.key('home')
                    continue
                first = selected(1)
                assert driver.wait(label='Level 1', role='text')
                subprocess.run(['import', '-window', window, str(output / f'play-map-{width}.png')], check=True)
                driver.key('up')
                selected(2)
                driver.key('home')
                first = selected(1)
                # Move forward along the road. The selected level stays in the panel.
                wheel = '4'
                subprocess.run(['xdotool', 'mousemove', str(width // 2), '150', 'click', '--repeat', '3', wheel], check=True)
                driver.wait_idle(frames=5)
                assert driver.wait(label='Level 1', role='text')
                moved = driver.find(key=33001, role='button', visible=True)
                assert not moved or abs(moved[0]['x'] - first['x']) + abs(moved[0]['y'] - first['y']) > 8, 'Wheel did not move map'
                driver.key('home')
                first = selected(1)
                second = driver.wait(key=33002, role='button', visible=True)
                dx = second['x'] - first['x']; dy = second['y'] - first['y']
                length = math.hypot(dx, dy)
                assert length > 10
                # A drag perpendicular to the incoming road must not pan away
                # from it; dragging along that road advances the camera.
                x0, y0 = width // 2, 180
                driver.drag((x0, y0), (x0 - dy * 70 / length, y0 + dx * 70 / length))
                driver.wait_idle(frames=6)
                stayed = selected(1)
                assert abs(stayed['x'] - first['x']) <= 3 and abs(stayed['y'] - first['y']) <= 3, ('Perpendicular drag left the rail', width, first, stayed, second)
                driver.drag((x0, y0), (x0 - dx * 120 / length, y0 - dy * 120 / length))
                driver.wait_idle(frames=6)
                assert driver.wait(label='Level 1', role='text')
                moved = driver.find(key=33001, role='button', visible=True)
                assert not moved or abs(moved[0]['x'] - first['x']) + abs(moved[0]['y'] - first['y']) > 8, ('Along-road drag did not move', width, first, second, moved)
                driver.key('home')
                selected(1)
                driver.key('end')
                # The completed short arm may expose a merge beyond the old
                # numeric prefix; End must choose an available destination.
                active = [node for node in driver.tree() if node.get('selected') and 33001 <= node.get('key', 0) <= 33175]
                assert len(active) == 1 and active[0]['enabled'], active
                driver.key('home')
                selected(1)
                reach_ends(width, height, f'frontier-{args.frontier}')
            driver.press(key=20122, role='button')
            driver.wait(contains='Level 1 / ', role='text', timeout=30)
            answer_level_updates(driver)
            driver.wait(label='Levels', role='button')
            driver.wait_idle(frames=5)
            driver.press(key=20002, role='button')
            assert_fullscreen_map(driver)
            selected(1)
        with app(profile, 'relaunch'):
            selected(1)
        (output / 'result.json').write_text(json.dumps({'viewports': [[390, 844], [960, 600]],
            'selected': 1, 'earned': args.frontier, 'wheel': not args.zoom_settle, 'drag_rail': not args.forks_only and not args.journey and not args.zoom_settle, 'fork_cursor_halves': args.forks_only,
            'reopen': True, 'relaunch': True, 'journey': journey_proof, 'zoom_settle': settle_proof, 'whole_map': reach_proof}, indent=2) + '\n')
    if args.zoom_settle:
        print('Private zoom-settle local test passed: two zoom transitions in both orientations, idle framing equals reveal, full selected hit and avatar above actual footer')
    elif args.journey:
        print('Private map journey local test passed: all 175 destinations in both orientations, rendered zoom, target spacing, painting coverage and fixed selection while browsing denser roads')
    elif args.forks_only:
        print('Private map camera local test passed: two orientations, cursor forks and reverse memory, stable selection, reopen and relaunch')
    else:
        print('Private map camera local test passed: two orientations, whole painting end to end at fresh and advanced progress, wheel, rail-constrained drag, selection, reopen and relaunch')


if __name__ == '__main__':
    main()
