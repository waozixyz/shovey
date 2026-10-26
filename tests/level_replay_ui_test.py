"""Exercise replay dots in the real native game on a private display."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    output = ROOT / 'build/level-replay-ui-test'
    output.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(subprocess.check_output(
        [str(ROOT / 'build/level-replay-test/native'), '--fixture'], text=True))

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
        profile = Path(temporary)
        records = profile / 'shovey'
        records.mkdir()
        for name, value in fixture.items():
            (records / name).write_text(value)
        (records / 'local.guide.seen').write_text('G1ffffffff')
        before_best = {name: value for name, value in fixture.items() if name.startswith('local.path.best.')}

        @contextlib.contextmanager
        def application(name):
            with (output / (name + '.log')).open('w') as log:
                environment = os.environ | {'KRYON_APP_DATA': str(profile), 'KRYON_ZOOM': '1',
                                             'SDL_AUDIODRIVER': 'dummy'}
                child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                                         env=environment, stdout=log, stderr=subprocess.STDOUT)
                try:
                    end = time.monotonic() + 20
                    windows = []
                    while time.monotonic() < end and not windows:
                        assert child.poll() is None, f'{name}: test app closed'
                        found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                               capture_output=True, text=True)
                        windows = found.stdout.split()
                        time.sleep(.05)
                    assert len(windows) == 1, 'Expected one window owned by this private test'
                    window = windows[0]
                    subprocess.run(['xdotool', 'windowsize', window, '430', '820'], check=True)
                    subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
                    time.sleep(1)
                    subprocess.run(['xdotool', 'key', '--window', window, 'Return'], check=True)
                    # The app acknowledges its initial board only after it opens.
                    end = time.monotonic() + 20
                    while time.monotonic() < end:
                        assert child.poll() is None
                        if list(records.glob('local.level.seen.*.3')):
                            break
                        time.sleep(.05)
                    assert list(records.glob('local.level.seen.*.3')), 'Game did not open the earned latest level'
                    # The standalone shell may ask for controls on its first open.
                    click(window, 110, 400)
                    yield window
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)

        def click(window, x, y):
            subprocess.run(['xdotool', 'mousemove', '--window', window, str(x), str(y)], check=True)
            subprocess.run(['xdotool', 'mousedown', '1'], check=True)
            time.sleep(.08)
            subprocess.run(['xdotool', 'mouseup', '1'], check=True)
            time.sleep(.25)

        def capture(window, name):
            path = output / name
            subprocess.run(['import', '-window', window, str(path)], check=True)
            with Image.open(path) as image:
                assert image.width == 430 and image.height >= 700, image.size
                return image.convert('RGB')

        # The production selector has three columns at this viewport. The
        # first card starts at (16,72), with its 8-pixel dot 13px from the edge.
        def dot_pixels(image, column=0):
            center_x = round(16 + column * (382 / 3 + 8) + 382 / 3 - 13)
            return sum(image.getpixel((x, y)) == (255, 226, 150)
                       for x in range(center_x - 4, center_x + 5) for y in range(81, 90))

        with application('changed') as window:
            click(window, 114, 26)  # The game's Levels control.
            time.sleep(1)
            changed = capture(window, 'changed-dot.png')
            assert dot_pixels(changed) >= 20, 'Missing dot on changed level 1'
            assert dot_pixels(changed, 1) == 0, 'Unchanged level 2 has a dot'
            click(window, 70, 130)  # Open level 1, without moving or winning.
            assert list(records.glob('local.level.seen.*.1')), 'Opening did not acknowledge level 1'
            first = json.loads((ROOT / 'levels/approved.json').read_text())['levels'][0]['solution'][0]
            subprocess.run(['xdotool', 'key', '--window', window,
                            ('Left', 'Up', 'Right', 'Down')[int(first)]], check=True)
            time.sleep(.25)
            attempt = json.loads((records / 'local.path.meta').read_text())
            assert attempt['actions'] > 0, 'Test move was not recorded'
            click(window, 114, 26)
            opened = capture(window, 'opened-no-dot.png')
            assert dot_pixels(opened) == 0, 'Dot survived opening'
            click(window, 350, 32)  # Continue retains this exact attempt.
            continued = json.loads((records / 'local.path.meta').read_text())
            assert continued == attempt, 'Continue changed the active map or route'

        with application('reopened') as window:
            click(window, 114, 26)
            reopened = capture(window, 'reopened-no-dot.png')
            assert dot_pixels(reopened) == 0, 'Dot returned after restarting'
        for name, value in before_best.items():
            assert (records / name).read_text() == value, 'Opening changed saved winning evidence'
        campaign = (records / 'local.campaign').read_text()
        start = 6 if campaign.startswith('C5') else 4
        assert campaign[start:start + 2] == '11', 'Opening erased earned completions'
    print('Level replay UI local tests: dot on changed level only; opening and restart dismiss it; wins and routes preserved')


if __name__ == '__main__':
    main()
