"""Capture real star joins on a private display with disposable editor data."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    output = ROOT / 'build/star-merge-ui-test'
    output.mkdir(parents=True, exist_ok=True)
    for landscape in (False, True):
        label = 'landscape' if landscape else 'portrait'
        with tempfile.TemporaryDirectory(prefix=label + '-', dir=output) as folder:
            profile = Path(folder)
            for name in ('shovey', 'shovey-landscape'):
                shutil.copytree(ROOT / f'assets/{name}/sprites', profile / f'assets/{name}/sprites')
            drafts = profile / 'backup/editor-drafts'
            drafts.mkdir(parents=True)
            (drafts / 'place').write_text('1')
            (drafts / 'orientation').write_text(label)
            (profile / 'levels').mkdir()
            board, terrain = [0] * 240, [99] * 240
            for at in range(240):
                if at % 12 in (0, 11) or at // 12 in (0, 19):
                    terrain[at] = 95
            board[10 * 12 + 4] = 10
            board[10 * 12 + 5] = board[10 * 12 + 7] = 19
            if landscape:
                board[9 * 12 + 6] = 19
            board[16 * 12 + 8] = 7
            def rows(values):
                return [''.join(f'{kind:02x}' for kind in values[at:at + 12]) for at in range(0, 240, 12)]
            level = dict(number=1, cells=rows(board), tiles=rows(terrain), decorations=rows([0] * 240), solution='')
            (profile / 'levels/classic.json').write_text(json.dumps(dict(edition='classic', width=12, height=20, levels=[level]), indent=1) + '\n')
            (profile / 'levels/approved.json').write_text('{"levels":[]}\n')
            environment = {key: value for key, value in os.environ.items() if key not in
                           ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY')}
            environment.update(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
            with (output / (label + '.log')).open('w') as log:
                child = subprocess.Popen([str(args.binary.resolve()), '--no-auto-publish'], cwd=profile,
                                         env=environment, stdout=log, stderr=subprocess.STDOUT)
                try:
                    window = None
                    for _ in range(200):
                        assert child.poll() is None, 'Private editor closed before mapping'
                        found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], capture_output=True, text=True)
                        if found.stdout.split():
                            window = found.stdout.split()[0]
                            break
                        time.sleep(.025)
                    assert window and int(subprocess.check_output(['xdotool', 'getwindowpid', window])) == child.pid
                    subprocess.run(['xdotool', 'windowfocus', window], check=True)
                    subprocess.run(['xdotool', 'windowsize', window, '1500', '1000'], check=True)
                    time.sleep(.15)
                    subprocess.run(['xdotool', 'key', '--window', window, 'Tab'], check=True)
                    time.sleep(.15)
                    if landscape:
                        # Logical right is visible up in the turned board.
                        key = 'Up'
                        crop = (8, 110, 1120, 995)
                    else:
                        key = 'Right'
                        crop = (290, 470, 760, 690)
                    def capture(name):
                        path = output / f'{label}-{name}.png'
                        subprocess.run(['import', '-window', window, str(path)], check=True)
                        with Image.open(path) as image:
                            return image.convert('RGB').crop(crop)
                    before = capture('before')
                    subprocess.run(['xdotool', 'key', '--window', window, key], check=True)
                    start = time.monotonic()
                    time.sleep(.08)
                    first = capture('joining')
                    time.sleep(max(0, .28 - (time.monotonic() - start)))
                    second = capture('glints')
                    time.sleep(max(0, .85 - (time.monotonic() - start)))
                    after = capture('cleared')
                    assert child.poll() is None, 'Star effect closed the editor'
                    assert ImageChops.difference(before, after).getbbox(), 'Stars were not removed'
                    assert ImageChops.difference(first, after).getbbox(), 'No visible joining frame'
                    assert ImageChops.difference(first, second).getbbox(), 'The effect did not animate'
                    text = (output / (label + '.log')).read_text()
                    assert 'frame could not' not in text and 'could not finish' not in text, text
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)
    print('Private star animation: two-star portrait and group landscape joins animate and clear without frame errors')


if __name__ == '__main__':
    main()
