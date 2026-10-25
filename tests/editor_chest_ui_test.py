"""The private selector opens the existing level-29 chest from either view."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
BINARY = Path(os.environ.get('SHOVEY_EDITOR', ROOT / 'build/private-editor/shovey-level-editor'))
ADMIN = os.environ.get('SHOVEY_ADMIN_TEST') == '1'
OUTPUT = ROOT / 'build/editor-chest-test'
OUTPUT.mkdir(parents=True, exist_ok=True)


def wait(predicate, message):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(.025)
    raise AssertionError(message)


with tempfile.TemporaryDirectory(dir=OUTPUT, prefix='profile-') as temporary:
    profile = Path(temporary)
    drafts = profile / 'backup/editor-drafts'
    driver = profile / 'driver'
    for folder in (drafts, driver, profile / 'levels'):
        folder.mkdir(parents=True)
    for artwork in ('shovey', 'shovey-landscape'):
        shutil.copytree(ROOT / 'assets' / artwork / 'sprites', profile / 'assets' / artwork / 'sprites')
    cells, tiles = [12] * 240, [12] * 240
    cells[13], cells[14], tiles[13], tiles[14] = 10, 7, 0, 77
    cells[157], tiles[157] = 0, 78
    def rows(layer):
        return [''.join(f'{kind:02x}' for kind in layer[at:at + 12]) for at in range(0, 240, 12)]
    levels = dict(edition='classic', width=12, height=20, levels=[
        dict(number=number, cells=rows(cells), tiles=rows(tiles), decorations=rows([0] * 240), solution='2')
        for number in range(1, 176)])
    campaign = profile / 'levels/classic.json'
    campaign.write_text(json.dumps(levels, indent=1) + '\n')
    before = campaign.read_bytes()
    (drafts / 'orientation').write_text('portrait')
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY')}
    environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0',
                       KRYON_TEST_DRIVER=str(driver))
    serial = 0
    def command(verb, **fields):
        global serial
        serial += 1
        (driver / 'command.next').write_text('\t'.join([str(serial), verb] +
            [f'{name}={value}' for name, value in fields.items()]) + '\n')
        (driver / 'command.next').replace(driver / 'command')
        def answered():
            if child.poll() is not None:
                raise AssertionError('Editor exited during its private test')
            reply = driver / 'reply'
            if not reply.exists():
                return None
            value = json.loads(reply.read_text())
            reply.unlink()
            return value if value.get('serial') == serial else None
        result = wait(answered, f'No editor reply for {verb}')
        assert result.get('ok'), result
        return result
    def nodes():
        return command('tree').get('nodes', [])
    def showing(label):
        return any(node.get('label') == label for node in nodes())
    def chest_shown():
        return any(node.get('detail', '').endswith('/chest-closed.png') for node in nodes())
    def press(label):
        node = next(node for node in nodes() if node.get('label') == label and node.get('visible'))
        x = int(node['visible_x'] + node['visible_width'] / 2)
        y = int(node['visible_y'] + node['visible_height'] / 2)
        subprocess.run(['xdotool', 'mousemove', '--window', window, str(x), str(y), 'mousedown', '1'], check=True)
        time.sleep(.08)
        subprocess.run(['xdotool', 'mouseup', '1'], check=True)
        time.sleep(.15)

    with (OUTPUT / ('admin.log' if ADMIN else 'private.log')).open('w') as log:
        child = subprocess.Popen([str(BINARY), '28'], cwd=profile, env=environment,
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            wait(lambda: showing('Level 28 of 175'), 'Editor did not start on level 28')
            window = wait(lambda: subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                          capture_output=True, text=True).stdout.split(), 'No private editor window')[0]
            subprocess.run(['xdotool', 'windowfocus', window], check=True)
            for mode in ('Levels', 'Map'):
                press('Level 28 of 175')
                if mode == 'Map':
                    press('Map')
                if ADMIN:
                    assert not showing('29a'), 'Public editor exposed private chest shortcut'
                    press('Level 28 of 175')
                    continue
                wait(lambda: showing('29a'), f'29a absent from {mode} selector')
                press('29a')
                wait(lambda: showing('Secret chest 29a'), '29a did not open chest context')
                assert (drafts / 'place').read_text().strip() == '29', '29a created a second board'
                wait(chest_shown, 'The actual chest sprite is missing in edit mode')
                press('Play (Tab)')
                wait(chest_shown, 'The actual chest sprite is missing in play mode')
                press('Edit (Tab)')
                press('Previous')
                wait(lambda: showing('Level 28 of 175'), 'Normal navigation retained chest context')
            assert campaign.read_bytes() == before, 'Selector changed the campaign'
            assert not (drafts / '178.hex').exists(), 'Shortcut created a duplicate draft'
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
print('Public editor excludes 29a' if ADMIN else
      'Private Map and Levels open canonical 29 via 29a; chest appears in edit/play, campaign unchanged')
