"""An approved level can publish while the editor remains usable."""
import json
import os
from pathlib import Path
import subprocess
import time
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/developer-editor-approval-test'
profile = output / 'profile'
drafts = profile / 'backup/editor-drafts'
for folder in (drafts, profile / 'levels', profile / 'scripts', profile / 'backup/redesign', profile / 'backup/original'):
    folder.mkdir(parents=True, exist_ok=True)
for path in drafts.iterdir():
    path.unlink()
(drafts / 'orientation').write_text('portrait')
if not (profile / 'assets').exists():
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
pieces = [12] * 240
pieces[13], pieces[14] = 10, 7
tiles = [kind if kind == 12 else 77 if kind == 7 else 0 for kind in pieces]
def rows(layer):
    return [''.join(f'{kind:02x}' for kind in layer[at:at + 12]) for at in range(0, 240, 12)]
level = dict(number=1, cells=rows(pieces), solution='2')
(profile / 'backup/editor-publish.json').unlink(missing_ok=True)
(profile / 'backup/original/classic-levels.zi').write_text('number == 73 { return "' + ''.join(rows(pieces)) + '" }')
(profile / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
(profile / 'levels/classic.json').write_text(json.dumps(dict(
    edition='classic', width=12, height=20, levels=[level, dict(level, number=2)]), indent=1) + '\n')
campaign = dict(levels=[dict(level, number=n, tiles=rows(tiles), decorations=rows([0] * 240))
                       for n in range(1, 24)])
(profile / 'levels/approved.json').write_text(json.dumps(campaign))
(drafts / 'publish-status').write_text('Published')
(drafts / '001.published').write_text(''.join(rows(pieces) + rows(tiles)) + '00' * 240)
(profile / 'scripts/editor_actions.py').write_text('''from pathlib import Path
import sys, time
root = Path('backup/editor-drafts')
(root / 'worker-started').write_text(' '.join(sys.argv[1:]))
time.sleep(2)
(root / 'worker-done').write_text('done')
''')
environment = {k: v for k, v in os.environ.items()
               if k not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
with (output / 'app.log').open('w') as log:
    child = subprocess.Popen([str(ROOT / 'build/private-editor/shovey-level-editor'), '1'],
                             cwd=profile, env=environment, stdout=log, stderr=subprocess.STDOUT)
    try:
        for attempt in range(300):
            windows = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                     capture_output=True, text=True).stdout.split()
            if windows:
                break
            assert child.poll() is None
            time.sleep(0.05)
        assert windows
        window = windows[0]
        def click(x, y):
            subprocess.run(['xdotool', 'mousemove', '--window', window, str(x), str(y), 'click', '1'], check=True)
        time.sleep(0.6)
        subprocess.run(['xdotool', 'windowfocus', window], check=True)
        click(100, 28)
        time.sleep(0.2)
        def map_colors():
            subprocess.run(['xdotool', 'mousemove', '--window', window, '4', '4'], check=True)
            shot = output / 'approvals-map.png'
            subprocess.run(['import', '-window', window, str(shot)], check=True)
            with Image.open(shot).convert('RGB') as image:
                width, height = image.size
                cell_width = (width - 16 - 4 * 14) / 15
                cell_height = (height - 96 - 28 - 4 * 11) / 12
                return [image.getpixel((int(14 + (n - 1) % 15 * (cell_width + 4)),
                                        int(122 + (n - 1) // 15 * (cell_height + 4))))
                        for n in range(1, 176)]
        purple = (159, 111, 209)
        colors = map_colors()
        assert all(color == purple for color in colors[:23]), colors
        assert colors[23] != purple and colors[24] != purple
        campaign['levels'].append(dict(level, number=24, tiles=rows(tiles), decorations=rows([0] * 240)))
        (profile / 'levels/approved.json').write_text(json.dumps(campaign))
        (drafts / 'publish-status').write_text('Updating…')
        time.sleep(0.7)
        colors = map_colors()
        assert all(color == purple for color in colors[:24]) and colors[24] != purple, colors
        click(100, 28)
        click(350, 66)  # Up-to-date levels have a disabled approval control.
        time.sleep(0.2)
        assert not (drafts / 'worker-started').exists()
        (drafts / '001.published').unlink()
        (drafts / 'publish-status').write_text('Update failed. Retry.')
        time.sleep(0.7)
        click(350, 66)  # A failed unpublished approval can still retry.
        for attempt in range(40):
            if (drafts / 'worker-started').exists():
                break
            time.sleep(0.025)
        assert (drafts / 'worker-started').read_text() == 'update 1'
        assert not (drafts / 'worker-done').exists()
        click(480, 28)  # Next is usable before publication completes.
        time.sleep(0.15)
        assert (drafts / 'place').read_text().strip() == '2'
        assert not (drafts / 'worker-done').exists()
        subprocess.run(['import', '-window', window, str(output / 'editor.png')], check=True)
        for attempt in range(100):
            if (drafts / 'worker-done').exists():
                break
            time.sleep(0.025)
        assert (drafts / 'worker-done').exists()
        click(390, 28)  # Return to the approved board.
        time.sleep(0.15)
        click(1300, 174)  # Moss floor, before every wall brush.
        time.sleep(0.15)
        click(476, 615)  # Cosmetic edit under Shovey preserves the winning route.
        for attempt in range(80):
            proof = drafts / '001.proof'
            if proof.exists() and proof.read_text().splitlines()[0][480 + 13 * 2:482 + 13 * 2] == '67':
                break
            time.sleep(0.05)
        # A prior approval without a published board cannot publish edits
        # automatically. The first publication needs the Approve click.
        assert not (drafts / '001.approval-request').exists()
        click(350, 66)
        for attempt in range(120):
            if (drafts / '001.approval-request').exists():
                break
            time.sleep(0.05)
        requested = (drafts / '001.approval-request').read_text().splitlines()[0]
        assert requested[480 + 13 * 2:482 + 13 * 2] == '67'
        assert (drafts / '001.approved').read_text() == requested
        for attempt in range(40):
            if (drafts / 'worker-started').read_text() == 'approve 1':
                break
            time.sleep(0.025)
        assert (drafts / 'worker-started').read_text() == 'approve 1'
        time.sleep(2.1)  # Let our detached disposable worker finish too.
        # Server-backed colors compare the open draft, not just its approval.
        (profile / 'backup/editor-publish.json').write_text('{}')
        base_board = ''.join(rows(pieces) + rows(tiles)) + '00' * 240
        server = dict(status='verified', boards=[requested] + [base_board] * 23)
        (drafts / 'server-campaign.json').write_text(json.dumps(server))
        click(100, 28)
        time.sleep(2.3)
        colors = map_colors()
        assert colors[0] == purple, colors[0]
        assert colors[72][0] > 2 * colors[72][1] and colors[72][0] > 2 * colors[72][2], colors[72]
        assert colors[73][1] > colors[73][0] and colors[73][1] > colors[73][2], colors[73]
        server['boards'][0] = base_board
        (drafts / 'server-campaign.json').write_text(json.dumps(server))
        time.sleep(2.3)
        assert map_colors()[0] == (218, 132, 167), 'Changed local board must be pink'
        click(100, 28)
        subprocess.run(['xdotool', 'mousemove', '--window', window, '4', '4'], check=True)
        subprocess.run(['import', '-window', window, str(output / 'diff-before.png')], check=True)
        click(460, 66)
        subprocess.run(['xdotool', 'mousemove', '--window', window, '4', '4'], check=True)
        subprocess.run(['import', '-window', window, str(output / 'diff.png')], check=True)
        with Image.open(output / 'diff-before.png').convert('RGB') as before, Image.open(output / 'diff.png').convert('RGB') as after:
            width, height = after.size
            area_width, area_height = width - 384, height - 92
            half = (area_height - 28) / 2
            cell = int(min(area_width / 12, (half - 26) / 20))
            x = int(8 + (area_width - cell * 12) / 2)
            y = int(84 + half + 54 + (half - 26 - cell * 20) / 2)
            def crop(at):
                left, top = x + at % 12 * cell, y + at // 12 * cell
                return (left, top, left + cell, top + cell)
            assert ImageChops.difference(before.crop(crop(13)), after.crop(crop(13))).getbbox(), 'Changed cell lacks its diff highlight'
            assert not ImageChops.difference(before.crop(crop(14)), after.crop(crop(14))).getbbox(), 'Diff highlighted an unchanged cell'
        (drafts / 'worker-started').unlink()
        (drafts / 'worker-done').unlink()
        click(350, 66)
        for attempt in range(40):
            if (drafts / 'worker-started').exists(): break
            time.sleep(.025)
        assert (drafts / 'worker-started').read_text() == 'update 1', 'Pink level cannot update'
        time.sleep(2.1)
        click(100, 28)
        server['status'] = 'unavailable'
        (drafts / 'server-campaign.json').write_text(json.dumps(server))
        time.sleep(2.3)
        assert map_colors()[0] == (144, 148, 148), 'An unavailable server cannot claim a match'
        server.update(status='verified', boards=[requested] + [base_board] * 23)
        (drafts / 'server-campaign.json').write_text(json.dumps(server))
        time.sleep(2.3)
        assert map_colors()[0] == purple
        click(100, 28)
        (drafts / 'worker-started').unlink()
        click(670, 66)
        for attempt in range(40):
            if (drafts / 'worker-started').exists(): break
            time.sleep(.025)
        assert (drafts / 'worker-started').read_text() == 'update-all 1'
        (drafts / 'publish-status').write_text('Checking levels 1/2…')
        time.sleep(.7)
        (drafts / 'worker-started').unlink()
        click(670, 66)
        time.sleep(.2)
        assert not (drafts / 'worker-started').exists(), 'Bulk checking allowed an overlapping update'
        time.sleep(2.1)
        (drafts / 'publish-status').write_text('Published · 1 not updated')
        time.sleep(.7)
        click(560, 66)
        for attempt in range(40):
            if (drafts / 'worker-started').exists(): break
            time.sleep(.025)
        assert (drafts / 'worker-started').read_text() == 'fix 1'
        subprocess.run(['import', '-window', window, str(output / 'fix-status.png')], check=True)
        with Image.open(output / 'fix-status.png').convert('RGB') as image:
            red, green, blue = image.getpixel((746, 75))
            assert green > red and green > blue, 'Known solution status was hidden by the GLM job'
        click(480, 28)
        assert (drafts / 'place').read_text().strip() == '2', 'GLM repair blocked navigation'
        time.sleep(2.1)
        print('Approval retries and saves passed; server matches purple, changed drafts pink, unverified gray; waiting 100% red and unknown/low similarity green')
    finally:
        if windows:
            subprocess.run(['import', '-window', windows[0], str(output / 'last.png')], check=True)
        child.terminate()
        child.wait(timeout=10)
