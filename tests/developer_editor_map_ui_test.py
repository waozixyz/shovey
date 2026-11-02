"""Private journey selection previews real layered drafts without opening them.

Run under a private Xvfb display; the editor gets disposable copied assets,
levels and drafts, and every input/capture targets its own process/window.
"""
import collections
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from world_map_test_support import private_environment

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
OUTPUT = ROOT / 'work/editor-map-test'
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
    driver = profile / 'driver'
    for folder in (drafts, driver, profile / 'levels'):
        folder.mkdir(parents=True)
    for folder in ('shovey/sprites', 'shovey-landscape/sprites', 'shovey/world-map'):
        if (ROOT / 'assets' / folder).exists():
            shutil.copytree(ROOT / 'assets' / folder, profile / 'assets' / folder)
    cells, tiles, decorations = [0] * 240, [77] * 240, [0] * 240
    cells[13], cells[14] = 10, 7
    def rows(layer):
        return [''.join(f'{kind:02x}' for kind in layer[at:at + 12]) for at in range(0, 240, 12)]
    campaign = dict(edition='classic', width=12, height=20, levels=[
        dict(number=number, cells=rows(cells), tiles=rows(tiles), decorations=rows(decorations), solution='2')
        for number in range(1, 176)])
    (profile / 'levels/classic.json').write_text(json.dumps(campaign, indent=1) + '\n')
    campaign_before = (profile / 'levels/classic.json').read_bytes()
    tiles[0], decorations[15] = 12, 57
    board = ''.join(f'{kind:02x}' for layer in (cells, tiles, decorations) for kind in layer)
    (drafts / '002.hex').write_text(board)
    (drafts / 'orientation').write_text(orientation)
    environment = private_environment(profile, {'SDL_VIDEODRIVER': 'x11',
        'SDL_AUDIODRIVER': 'dummy', 'KRYON_TEST_DRIVER': str(driver)})
    serial = 0

    def command(verb, **fields):
        global serial
        serial += 1
        (driver / 'command.next').write_text('\t'.join([str(serial), verb] +
            [f'{name}={value}' for name, value in fields.items()]) + '\n')
        (driver / 'command.next').replace(driver / 'command')

        def answered():
            assert child.poll() is None, 'Private test editor exited'
            reply = driver / 'reply'
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
        (profile / 'labels.json').write_text(json.dumps([
            {key: node.get(key) for key in ('label', 'visible', 'kind')}
            for node in result if node.get('label') and not node.get('detail', '').endswith('.png')][:80], indent=2))
        return result

    def showing(label):
        return any(node.get('label') == label and node.get('visible') for node in nodes())

    def press(label):
        node = next(node for node in nodes() if node.get('label') == label and node.get('visible'))
        x = int(node['visible_x'] + node['visible_width'] / 2)
        y = int(node['visible_y'] + node['visible_height'] / 2)
        subprocess.run(['xdotool', 'mousemove', '--window', window, str(x), str(y), 'mousedown', '1'], check=True)
        time.sleep(.08)
        subprocess.run(['xdotool', 'mouseup', '1'], check=True)
        time.sleep(.15)

    def key(code):
        name = {269: 'End', 268: 'Home', 78: 'n', 90: 'z', 256: 'Escape', 262: 'Right', 263: 'Left', 265: 'Up'}[code]
        subprocess.run(['xdotool', 'key', '--window', window, name], check=True)
        time.sleep(.15)

    def sprites(label):
        return collections.Counter(node.get('detail') for node in nodes()
                                   if node.get('label') == label and node.get('detail', '').endswith('.png'))

    with (profile / 'app.log').open('w') as log:
        child = subprocess.Popen([str(BINARY), '1', '--no-auto-publish'], cwd=profile,
                                 env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            window = wait(lambda: subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                          capture_output=True, text=True).stdout.split(), 'No private test window')[0]
            assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
            subprocess.run(['xdotool', 'windowsize', window, str(width), str(height)], check=True)
            subprocess.run(['xdotool', 'windowfocus', window], check=True)
            wait(lambda: showing('Level 1 of 175'), 'Wrong starting level')
            press('Play (Tab)')
            wait(lambda: showing('Edit (Tab)'), 'Playtest did not start')
            key(263)  # Record a non-winning move so undo has something to preserve.
            attempt = drafts / '001.attempt'
            before = wait(lambda: attempt.read_bytes() if attempt.exists() else None, 'No play attempt')
            assert len(before.rsplit(b'\n', 1)[-1]) == 1, 'Test move was not recorded'
            press('Level 1 of 175')
            wait(lambda: showing('Edit'), 'Map did not open during play')
            key(262)
            key(263)
            key(90)
            time.sleep(1.5)
            assert attempt.read_bytes() == before, 'Map input or hidden ticks changed play history'
            key(256)
            wait(lambda: showing('Edit (Tab)'), 'Cancel stopped the playtest')
            assert attempt.read_bytes() == before, 'Closing map caught up hidden ticks'
            key(90)
            assert attempt.read_bytes() == before[:-1], 'Play undo history was not preserved'
            press('Edit (Tab)')
            wait(lambda: showing('Play (Tab)'), 'Could not leave playtest')
            press('Level 1 of 175')
            wait(lambda: showing('Edit'), 'Map did not open by default')
            key(269)  # End reveals the final ordinary destination.
            wait(lambda: showing('Level 175'), 'Full journey is unreachable')
            wait(lambda: showing('175'), 'Final map marker was not revealed')
            key(268)
            manifest = json.loads((ROOT / 'assets/shovey/world-map/riverfold.json').read_text())
            edges = {(e['from'], e['to']) for e in manifest['edges']}
            for level in range(1, 176):
                if level > 1:
                    key(265 if (level - 1, level) in edges else 262)
                wait(lambda: showing(f'Level {level}'), f'Missing authored preview {level}')
                marker = next((n for n in nodes() if n.get('key') == 33000 + level and n.get('visible')), None)
                assert marker is not None, f'Missing authored waypoint {level}'
                actual_preview = wait(lambda: sprites('Level preview'), f'Missing layered board {level}')
                assert sum(actual_preview.values()) >= 242, (level, actual_preview)
            # Editor aliases must reveal their corresponding detached artwork.
            manifest = json.loads((ROOT / 'assets/shovey/world-map/riverfold.json').read_text())
            for label in ('175a', '175b', '29a'):
                if label == '29a':
                    key(268)
                    for level in range(2, 30):
                        key(265 if (level - 1, level) in edges else 262)
                key(78)
                wait(lambda: showing('Level ' + label), 'Missing private secret preview ' + label)
                index = next(i for i, panel in enumerate(manifest['panels']) if panel['id'] == 'secret-' + label)
                assert any(n.get('key') == 60000 + index for n in nodes()), 'Private alias islet artwork missing'
            assert (drafts / 'place').read_text().strip() == '1'
            key(268)
            wait(lambda: showing('2'), 'Nearby map marker was not revealed')
            press('2')  # Browse to draft 2, without opening it.
            wait(lambda: showing('Level 2'), 'Focused destination preview did not change')
            preview = wait(lambda: sprites('Level preview'), 'No actual board sprite preview')
            assert sum(preview.values()) == 243, preview  # 240 floors, two pieces, one decoration.
            assert (drafts / 'place').read_text().strip() == '1', 'Browsing opened another level'
            key(262)
            wait(lambda: showing('Level 3'), 'Shared map keyboard navigation did not focus next destination')
            key(263)
            wait(lambda: showing('Level 2'), 'Shared map keyboard navigation did not return to draft')
            assert sprites('Level preview') == preview
            key(90)  # Undo belongs to the open board, and must be ignored while browsing.
            assert (drafts / '002.hex').read_text() == board, 'Preview changed the draft'
            assert (profile / 'levels/classic.json').read_bytes() == campaign_before
            subprocess.run(['import', '-window', window, str(OUTPUT / f'{orientation}.png')], check=True)
            key(256)  # Cancel preserves current level.
            wait(lambda: showing('Play (Tab)'), 'Cancel did not return to editing')
            assert (drafts / 'place').read_text().strip() == '1'
            press('Level 1 of 175')
            wait(lambda: showing('Level 1') and showing('Edit'), 'Reopen did not focus current board')
            key(78)
            wait(lambda: showing('Level 2'), 'Preview focus was not restored')
            press('Edit')
            wait(lambda: (drafts / 'place').read_text().strip() == '2', 'Edit did not use existing open path')
            actual = wait(lambda: sprites('New level'), 'Opened board has no sprites')
            assert actual == preview, 'Preview differs from actual draft renderer'
            # The existing save path may immediately prove and save a cosmetic
            # draft. Either representation must retain its exact three layers.
            saved = json.loads((profile / 'levels/classic.json').read_text())
            if (drafts / '002.hex').exists():
                assert (drafts / '002.hex').read_text() == board
            else:
                assert ''.join(''.join(saved['levels'][1][name])
                               for name in ('cells', 'tiles', 'decorations')) == board
            assert saved['levels'][:1] == campaign['levels'][:1]
            assert saved['levels'][2:] == campaign['levels'][2:]
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

print('Private map selector: portrait and landscape, full journey, actual layered draft preview, '
      'cancel and explicit Edit preserve current level and draft data')
