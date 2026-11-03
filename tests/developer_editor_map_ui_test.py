"""Verify the private editor selector gives its whole region to the map.

Run under a private Xvfb display. Each editor owns a disposable profile, and
every input or capture targets only that process's window.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from world_map_test_support import private_environment


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'work/editor-map-test'
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
subprocess.run(['git', 'check-ignore', '-q', str(OUTPUT)], cwd=ROOT, check=True)
OUTPUT.mkdir(parents=True, exist_ok=True)
BINARY = ROOT / 'build/private-editor/shovey-level-editor'


def wait(predicate, message):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(.04)
    raise AssertionError(message)


for width, height, orientation in ((1500, 1000, 'landscape'), (780, 1100, 'portrait')):
    profile = OUTPUT / orientation
    if profile.exists():
        shutil.rmtree(profile)
    drafts = profile / 'backup/editor-drafts'
    driver_folder = profile / 'driver'
    for folder in (drafts, driver_folder, profile / 'levels'):
        folder.mkdir(parents=True)
    for folder in ('shovey/sprites', 'shovey-landscape/sprites', 'shovey/world-map'):
        shutil.copytree(ROOT / 'assets' / folder, profile / 'assets' / folder)
    (drafts / 'orientation').write_text(orientation)
    (drafts / 'place').write_text('1')
    campaign = dict(edition='classic', width=12, height=20, levels=[
        dict(number=number, cells=['00' * 12] * 20, tiles=['4d' * 12] * 20,
             decorations=['00' * 12] * 20, solution='2')
        for number in range(1, 176)
    ])
    (profile / 'levels/classic.json').write_text(json.dumps(campaign, indent=1) + '\n')
    environment = private_environment(profile, {'SDL_VIDEODRIVER': 'x11',
        'SDL_AUDIODRIVER': 'dummy', 'KRYON_TEST_DRIVER': str(driver_folder)})
    serial = 0

    def command(verb, **fields):
        global serial
        serial += 1
        (driver_folder / 'command.next').write_text('\t'.join([str(serial), verb] +
            [f'{name}={value}' for name, value in fields.items()]) + '\n')
        (driver_folder / 'command.next').replace(driver_folder / 'command')

        def answered():
            assert child.poll() is None, 'Private test editor exited'
            reply = driver_folder / 'reply'
            if not reply.exists():
                return None
            value = json.loads(reply.read_text())
            reply.unlink()
            return value if value.get('serial') == serial else None

        result = wait(answered, f'No reply for {verb}')
        assert result.get('ok'), result
        return result

    def nodes():
        result = command('tree').get('nodes', [])
        (profile / 'tree.json').write_text(json.dumps(result, indent=1) + '\n')
        return result

    def showing(label):
        return any(node.get('label') == label and node.get('visible') for node in nodes())

    def find(predicate):
        return next(node for node in nodes() if predicate(node) and node.get('visible'))

    def pointer(x, y, click=False, button=1):
        subprocess.run(['xdotool', 'mousemove', '--window', window,
                        str(int(x)), str(int(y))], check=True)
        if click:
            subprocess.run(['xdotool', 'click', '--window', window, '--repeat', '5',
                            '--delay', '50', str(button)], check=True)
            time.sleep(.15)

    def press(label):
        node = find(lambda item: item.get('label') == label and item.get('kind') == 'button')
        pointer(node['visible_x'] + node['visible_width'] / 2,
                node['visible_y'] + node['visible_height'] / 2, click=True)

    def key(name):
        subprocess.run(['xdotool', 'key', '--window', window, name], check=True)
        time.sleep(.15)

    with (profile / 'app.log').open('w') as log:
        child = subprocess.Popen([str(BINARY), '1', '--no-auto-publish'], cwd=profile,
                                 env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            window = wait(lambda: subprocess.run(['xdotool', 'search', '--onlyvisible',
                '--pid', str(child.pid)], capture_output=True, text=True).stdout.split(),
                'No private test window')[0]
            assert subprocess.check_output(['xdotool', 'getwindowpid', window],
                                           text=True).strip() == str(child.pid)
            subprocess.run(['xdotool', 'windowmove', window, '0', '0'], check=True)
            subprocess.run(['xdotool', 'windowsize', '--sync', window,
                            str(width), str(height)], check=True)
            wait(lambda: showing('Level 1 of 175'), 'Editor did not start on level 1')
            press('Level 1 of 175')
            map_node = wait(lambda: next((node for node in nodes()
                if node.get('key') == 20105 and node.get('visible')), None), 'Map did not open')
            expected = (8, 116, width - 16, height - 124)
            actual = tuple(round(map_node[name]) for name in
                           ('visible_x', 'visible_y', 'visible_width', 'visible_height'))
            assert actual == expected, (orientation, map_node, expected)
            assert not any(node.get('key') == 76000 for node in nodes()), 'Board preview rendered'
            assert not showing('Level preview'), 'Preview title rendered'
            assert showing('Map') and showing('Levels'), 'Selector controls were lost'
            edit = find(lambda item: item.get('label') == 'Edit' and
                        item.get('kind') == 'button')
            assert edit['visible_x'] >= map_node['visible_x'], edit
            assert edit['visible_x'] + edit['visible_width'] <= (
                map_node['visible_x'] + map_node['visible_width']), edit

            marker = find(lambda item: item.get('key') == 33002 and
                          item.get('kind') == 'button')
            pointer(marker['visible_x'] + marker['visible_width'] / 2,
                    marker['visible_y'] + marker['visible_height'] / 2, click=True)
            wait(lambda: find(lambda item: item.get('key') == 33002 and
                              item.get('selected')), 'Selected dot did not receive focus')
            assert (drafts / 'place').read_text().strip() == '1', 'Browsing opened the board'
            key('Return')
            wait(lambda: showing('Level 2 of 175'), 'Keyboard Edit did not open focused board')
            assert not any(node.get('key') == 20105 for node in nodes()), 'Map stayed open'

            press('Level 2 of 175')
            map_node = wait(lambda: next((node for node in nodes()
                if node.get('key') == 20105 and node.get('visible')), None),
                'Map did not reopen')
            before = find(lambda item: item.get('key') == 33002 and
                          item.get('kind') == 'button')
            old_area_x = map_node['visible_x'] + map_node['visible_width'] * (
                .82 if orientation == 'landscape' else .5)
            old_area_y = map_node['visible_y'] + map_node['visible_height'] * (
                .5 if orientation == 'landscape' else .75)
            pointer(old_area_x, old_area_y)
            subprocess.run(['xdotool', 'mousedown', '--window', window, '1'], check=True)
            time.sleep(.05)
            subprocess.run(['xdotool', 'mousemove', '--window', window,
                            str(int(old_area_x - 180)), str(int(old_area_y - 40))], check=True)
            time.sleep(.08)
            subprocess.run(['xdotool', 'mouseup', '--window', window, '1'], check=True)
            time.sleep(.2)
            dragged = find(lambda item: item.get('key') == 33002 and
                           item.get('kind') == 'button')
            # The v5 map has no free camera: drags follow the painted road.
            # Landscape scrolls sideways; the portrait painting fills the
            # width, so a sideways drag cannot pan there.
            if orientation == 'landscape':
                assert dragged['visible_x'] < before['visible_x'] - 24, (before, dragged)
            else:
                assert abs(dragged['visible_x'] - before['visible_x']) <= 1, (before, dragged)
            # Portrait starts clamped at the map's foot, so the road must pass
            # the camera's centre before the painting moves: drag farther there,
            # clear of the dots on the left.
            vertical_x = map_node['visible_x'] + map_node['visible_width'] * (
                .5 if orientation == 'landscape' else .8)
            vertical_y = old_area_y if orientation == 'landscape' else (
                map_node['visible_y'] + map_node['visible_height'] * .25)
            vertical_drag = 180 if orientation == 'landscape' else 440
            pointer(vertical_x, vertical_y)
            subprocess.run(['xdotool', 'mousedown', '--window', window, '1'], check=True)
            time.sleep(.05)
            subprocess.run(['xdotool', 'mousemove', '--window', window,
                            str(int(vertical_x)), str(int(vertical_y + vertical_drag))], check=True)
            time.sleep(.08)
            subprocess.run(['xdotool', 'mouseup', '--window', window, '1'], check=True)
            time.sleep(.2)
            vertical = find(lambda item: item.get('key') == 33002 and
                            item.get('kind') == 'button')
            # The landscape painting fills the height, so a vertical drag
            # cannot pan up or down there; portrait scrolls vertically.
            if orientation == 'landscape':
                assert abs(vertical['visible_y'] - dragged['visible_y']) <= 1, (dragged, vertical)
            else:
                assert abs(vertical['visible_y'] - dragged['visible_y']) >= 24, (dragged, vertical)
            assert (drafts / 'place').read_text().strip() == '2', 'Panning changed selection'
            pointer(old_area_x, old_area_y)
            subprocess.run(['xdotool', 'click', '4'], check=True)
            time.sleep(.2)
            wheeled = find(lambda item: item.get('key') == 33002 and
                           item.get('kind') == 'button')
            # The wheel also follows the road, sideways in landscape.
            assert abs(wheeled['visible_x'] - vertical['visible_x']) + abs(
                wheeled['visible_y'] - vertical['visible_y']) >= 16, (vertical, wheeled)
            subprocess.run(['import', '-window', window,
                            str(OUTPUT / f'{orientation}.png')], check=True)
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

print('Private editor selector: full map in portrait and landscape; no board preview; '
      'dot focus, keyboard Edit, wheel and road-following drag all work')
