"""Traverse the complete shipped journey on a private display and measure RSS.

The test uses disposable saves. It checks all ordinary destinations and native
panels, then opens explicitly discovered detached rooms from the same map.
"""
import argparse
import contextlib
import hashlib
import math
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image
from world_map_test_support import private_environment

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    parser.add_argument('--secrets-only', action='store_true')
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    output = ROOT / 'work/world-map-journey-test'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'assets/shovey/world-map/riverfold.json').read_text())
    panels = manifest['panels']
    assert panels and all((ROOT / panel['path']).is_file() for panel in panels)
    assert manifest['generatedPanelCount'] == manifest['panelCount'], 'The full artwork is not ready'
    measured = {node['level'] for node in manifest['nodes'] if node.get('roadCenterMeasured')}
    assert measured == set(range(1, 176)), 'Painted trail coordinates are incomplete'
    for panel in panels:
        assert panel['status'] == 'generated', panel['id']
        assert hashlib.file_digest((ROOT / panel['path']).open('rb'), 'sha256').hexdigest() == panel['sha256']
        source, world = panel['source'], panel['worldBounds']
        with Image.open(ROOT / panel['path']) as native:
            assert native.size == (panel['nativeWidth'], panel['nativeHeight']), panel['id']
        assert source['x'] >= 0 and source['y'] >= 0 and source['width'] > 0 and source['height'] > 0
        assert source['x'] + source['width'] <= panel['nativeWidth'] + .001, panel['id']
        assert source['y'] + source['height'] <= panel['nativeHeight'] + .001, panel['id']
        assert abs(source['width'] / source['height'] - world['width'] / world['height']) < .001, panel['id']
    review = json.loads((ROOT / 'work/riverfold-map-art/world-projection/visual-review.json').read_text())
    assert review['candidate']['sha256'] == manifest['candidateSha256']
    assert review['counts']['classicNodes'] == 175 and review['counts']['crossings'] == 15
    secret_panels = {60000 + index for index, panel in enumerate(panels) if panel['discoveredOnly']}
    provenance = {str(path.relative_to(ROOT)): hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
                  for path in [ROOT / 'src/world_map_art.zi', ROOT / 'src/world_map_layout.zi',
                               ROOT / 'src/world_map_view.zi', ROOT / 'assets/shovey/world-map/riverfold.json']}
    provenance['binary'] = hashlib.file_digest(args.binary.open('rb'), 'sha256').hexdigest()
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver
    from shovey_standalone_ui_test import answer_cover_question, answer_level_updates
    driver = UiDriver(output / 'driver')
    peak_kib = 0

    def peak(child):
        nonlocal peak_kib
        with open(f'/proc/{child.pid}/status') as status:
            for line in status:
                if line.startswith('VmHWM:'):
                    peak_kib = max(peak_kib, int(line.split()[1]))
                    break

    @contextlib.contextmanager
    def application(profile, name, width, height):
        with (output / f'{name}.log').open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()),
                stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, output / f'{name}.log')
            try:
                driver.wait(label='Play', role='button', timeout=60)
                window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0]
                assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                answer_level_updates(driver)
                if driver.find(label='How do you want to move?', role='text'):
                    driver.press(label='Swipe and tap')
                    driver.wait(label='Got it', role='button')
                if driver.find(label='Got it', role='button'):
                    driver.press(label='Got it')
                driver.wait(label='Levels', role='button', timeout=30)
                yield child, window
                peak(child)
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)

    for width, height in ((390, 844), (960, 600)):
        profile = output / f'profile-{width}'
        profile.mkdir(exist_ok=True)
        # Bootstrap a genuine campaign record, then seed its ordinary progress.
        with application(profile, f'bootstrap-{width}', width, height):
            pass
        records = profile / 'games/arcade.shovey/records'
        campaign = records / 'local.campaign'
        text = campaign.read_text()
        header, marks = (6, 1000) if text.startswith('C5') else (4, 175)
        campaign.write_text(text[:2] + f'{175:0{header - 2}x}' + '1' * 174 + '0' * (marks - 174) + text[header + marks:])
        for key in ('local.secret29a', 'local.secret175a', 'local.secret175b'):
            (records / key).unlink(missing_ok=True)
        edges = {(edge['from'], edge['to']) for edge in manifest['edges']}
        if not args.secrets_only:
            with application(profile, f'journey-{width}', width, height) as (child, window):
                driver.press(label='Levels', role='button')
                driver.wait(key=33001, role='button')
                driver.key('home')
                seen_levels, seen_panels, captures = set(), set(), set()
                edges = {(edge['from'], edge['to']) for edge in manifest['edges']}
                forks = {edge['from'] for edge in manifest['edges']
                         if sum(other['from'] == edge['from'] for other in manifest['edges']) == 2}
                def reveal(level):
                    driver.key('home')
                    for current in range(1, level):
                        driver.key('up' if (current, current + 1) in edges else 'right')
                    return driver.wait(key=33000 + level, role='button', visible=True)
                for level in range(1, 176):
                    if level > 1:
                        driver.key('up' if (level - 1, level) in edges else 'right')
                    marker = driver.wait(key=33000 + level, role='button', visible=True)
                    assert marker['selected'], (level, marker)
                    driver.wait_idle(frames=4, timeout=3)
                    nodes = driver.tree()
                    peak(child)
                    seen_levels.add(level)
                    current_panels = {node['key'] - 60000 for node in nodes
                        if node.get('visible') and 60000 <= node.get('key', 0) < 60000 + len(panels)}
                    seen_panels |= current_panels
                    assert not any(node.get('key') in secret_panels | {34001, 34002, 34003} for node in nodes), 'Undiscovered islet leaked'
                    # Actual owned-window captures at every regional landing and fork.
                    region = manifest['nodes'][level - 1]['region']
                    if region not in captures or level in forks or level - 1 in forks:
                        subprocess.run(['import', '-window', window, str(output / f'journey-{width}-level-{level:03}.png')], check=True)
                        captures.add(region)
                    # Sweep both horizontal directions through authored water bounds,
                    # then reveal the unchanged focused waypoint again.
                    if level in {1, 29, 75, 112, 175}:
                        for direction in ('a', 'd'):
                            for _ in range(math.ceil(manifest['worldWidth'] / 195) + 1):
                                driver.key(direction)
                            driver.wait_idle(frames=3)
                            subprocess.run(['import', '-window', window, str(output / f'outer-{width}-{level}-{direction}.png')], check=True)
                        reveal(level)
                assert seen_levels == set(range(1, 176))
                assert len(captures) == 16
                expected_panels = set(range(len(panels))) - {key - 60000 for key in secret_panels}
                # Small connectors may be off-screen while endpoints are centered;
                # record them for the explicit centerline sweep below.
                for edge in manifest['edges']:
                    first = manifest['nodes'][edge['from'] - 1]
                    last = manifest['nodes'][edge['to'] - 1]
                    if first['region'] == last['region']:
                        continue
                    marker = reveal(edge['from'])
                    # Follow painted intermediate bends in screen-sized steps.
                    scale = min(width - 32, 390) / 390
                    viewport = next(n for n in driver.tree() if n.get('key') == 20105)
                    page_step = viewport['height'] * .8
                    for at, point in enumerate(edge['points']):
                        dx, dy = (point[0] - first['x']) * scale, (point[1] - first['y']) * scale
                        for _ in range(round(abs(dx) / (min(width - 32, 390) / 2))):
                            driver.key('d' if dx > 0 else 'a')
                        for _ in range(round(abs(dy) / page_step)):
                            driver.key('page_down' if dy > 0 else 'page_up')
                        driver.wait_idle(frames=3)
                        seen_panels |= {n['key'] - 60000 for n in driver.tree()
                                        if n.get('visible') and 60000 <= n.get('key', 0) < 60000 + len(panels)}
                        if at == len(edge['points']) // 2:
                            subprocess.run(['import', '-window', window, str(output / f'join-{width}-{first["region"]:02}.png')], check=True)
                        # Regional endpoints are not sibling arms: down/up reveals
                        # the same endpoint without replaying the entire journey.
                        driver.key('down')
                        driver.key('up')
                assert expected_panels <= seen_panels, f'Missing painted instances: {expected_panels - seen_panels}'
                driver.key('home')
                driver.press(key=33001, role='button')
                driver.wait(contains='Level 1 / ', role='text')
                driver.press(label='Levels', role='button')
                driver.press(key=20022, role='button')
                driver.wait(contains='Level 1 / ', role='text')
        # Navigate to each measured islet rather than assuming End reveals it.
        for secret in manifest['secrets']:
            (records / ('local.secret' + secret['id'])).write_text('1')
        with application(profile, f'discovered-{width}', width, height) as (child, window):
            driver.press(label='Levels', role='button')
            for secret in manifest['secrets']:
                driver.key('home')
                for current in range(1, secret['anchorLevel']):
                    driver.key('up' if (current, current + 1) in edges else 'right')
                anchor = manifest['nodes'][secret['anchorLevel'] - 1]
                delta = (secret['node']['x'] - anchor['x'], secret['node']['y'] - anchor['y'])
                for _ in range(round(abs(delta[0]) / 195)):
                    driver.key('d' if delta[0] > 0 else 'a')
                viewport = next(n for n in driver.tree() if n.get('key') == 20105)
                for _ in range(round(abs(delta[1]) * min(width - 32, 390) / 390 / (viewport['height'] * .8))):
                    driver.key('page_down' if delta[1] > 0 else 'page_up')
                key = {'175a': 34001, '175b': 34002, '29a': 34003}[secret['id']]
                room = driver.wait(key=key, role='button', visible=True)
                assert room['enabled'] and room['label'] == secret['id']
                subprocess.run(['import', '-window', window, str(output / f'detached-{width}-{secret["id"]}.png')], check=True)
                driver.press(key=key, role='button')
                driver.wait(contains=secret['id'], role='text')
                driver.wait(label='Levels', role='button')
                driver.press(label='Levels', role='button')
                peak(child)
    result = dict(levels=175, panels=len(panels), viewports=[[390, 844], [960, 600]], peak_rss_kib=peak_kib, provenance=provenance)
    if args.secrets_only:
        result.pop('levels')
        result.pop('panels')
        result['activated_rooms'] = ['29a', '175a', '175b']
    (output / ('secret-activation-result.json' if args.secrets_only else 'result.json')).write_text(json.dumps(result, indent=2) + '\n')
    scope = '3 discovered rooms activated in both viewports' if args.secrets_only else f'175 destinations, {len(panels)} native instances, detached discoveries'
    print(f'Map local UI test passed: {scope}; peak RSS {peak_kib / 1024:.1f} MiB')


if __name__ == '__main__':
    main()
