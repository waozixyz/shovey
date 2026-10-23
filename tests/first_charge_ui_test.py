"""Verify the first charge visibly bursts, then settles, on a private Xvfb."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/first-charge-ui-test'
OUT.mkdir(parents=True, exist_ok=True)
display = os.environ['DISPLAY']
assert display.startswith(':') and int(display[1:].split('.')[0]) >= 400
assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'

# Check the actual server, not just the display's number or the output path.
servers = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        if Path(args[0].decode()).name != 'Xvfb' or display.encode() not in args:
            continue
        parent = int((proc / 'stat').read_text().rsplit(')', 1)[1].split()[1])
        assert parent == os.getppid(), 'The X server must belong to this xvfb-run'
        assert proc.stat().st_uid == os.getuid()
        servers.append(int(proc.name))
    except (PermissionError, FileNotFoundError, ProcessLookupError):
        continue
assert len(servers) == 1, servers
server = servers[0]

binary = Path(os.environ.get('SHOVEY_EDITOR_BINARY', ROOT / 'build/private-editor/shovey-level-editor')).resolve()
pieces, tiles = [0] * 240, [0] * 240
for at in range(240):
    if at < 12 or at >= 228 or at % 12 in (0, 11):
        tiles[at] = 12
pieces[13], pieces[14], pieces[15], pieces[50] = 10, 27, 27, 7


def rows(values):
    return [''.join(f'{v:02x}' for v in values[start:start + 12]) for start in range(0, 240, 12)]


level = dict(number=1, cells=rows(pieces), tiles=rows(tiles), decorations=rows([0] * 240), solution='2333')
board = ''.join(level['cells'] + level['tiles'] + level['decorations'])


def cyan_pixels(path):
    # Only the lower, editable board; neither its status nor the reference board.
    picture = Image.open(path).convert('RGB').crop((8, 578, 1124, 992))
    rgb = picture.tobytes()
    return sum(g > 170 and b > 175 and g > r + 25 and b > r + 25
               for r, g, b in zip(rgb[::3], rgb[1::3], rgb[2::3]))


results = []
for orientation, step in (('portrait', 'Right'), ('landscape', 'Up')):
    profile = OUT / orientation
    (profile / 'levels').mkdir(parents=True, exist_ok=True)
    drafts = profile / 'backup/editor-drafts'
    drafts.mkdir(parents=True, exist_ok=True)
    for name in ('shovey', 'shovey-landscape'):
        shutil.copytree(ROOT / 'assets' / name, profile / 'assets' / name, dirs_exist_ok=True)
    (profile / 'levels/classic.json').write_text(json.dumps(dict(edition='classic', width=12, height=20,
        levels=[level, dict(level, number=2, solution='')]), indent=1) + '\n')
    (profile / 'levels/approved.json').write_text(json.dumps(dict(levels=[level])))
    (drafts / '001.hex').write_text(board)
    (drafts / '001.proof').write_text(board + '\n2333')
    (drafts / 'orientation').write_text(orientation)
    environment = {k: v for k, v in os.environ.items() if k not in
                   ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY')}
    environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    with (OUT / f'{orientation}.log').open('w') as log:
        child = subprocess.Popen([str(binary), '1'], cwd=profile, env=environment,
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            window = None
            for _ in range(200):
                found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid),
                                        '--name', '^Shovey level editor$'], capture_output=True, text=True)
                if found.stdout.split():
                    window = found.stdout.split()[0]
                    break
                assert child.poll() is None, f'Editor exited; see {log.name}'
                time.sleep(0.05)
            assert window, f'No owned editor window; see {log.name}'
            subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)

            def capture(name):
                os.kill(server, 0)
                assert int(subprocess.check_output(['xdotool', 'getwindowpid', window], text=True)) == child.pid
                path = OUT / f'{orientation}-{name}.png'
                subprocess.run(['import', '-window', window, str(path)], check=True, timeout=10)
                return path

            time.sleep(0.3)
            subprocess.run(['xdotool', 'key', '--window', window, 'Tab'], check=True)
            time.sleep(0.2)
            subprocess.run(['xdotool', 'key', '--window', window, step], check=True)
            bursts = []
            for i in range(3):
                time.sleep(0.06)
                bursts.append(capture(f'burst-{i}'))
            time.sleep(0.8)
            settled = capture('charged')
            baseline = cyan_pixels(settled)
            strongest = max(cyan_pixels(p) for p in bursts)
            assert strongest > baseline + 24, (orientation, strongest, baseline)
            # The fatal second touch still displays its own shock sequence.
            subprocess.run(['xdotool', 'key', '--window', window, step], check=True)
            time.sleep(0.15)
            capture('second-touch')
            time.sleep(1.35)
            capture('charred')
            results.append(dict(orientation=orientation, server_pid=server, display=display,
                                editor_pid=child.pid, window=window, binary=str(binary),
                                burst_cyan_pixels=strongest, settled_cyan_pixels=baseline))
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)

(OUT / 'capture-source.json').write_text(json.dumps(results, indent=2) + '\n')
print('Local UI tests: first-touch glow and sparks are visible and fade in portrait and landscape.')
