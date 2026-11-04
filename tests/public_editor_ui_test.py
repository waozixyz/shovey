"""Private-window public editor regression; every publication uses a fake callback."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image
from editor_ui_driver import EditorUiDriver

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/public-editor-create-only'

def wait(predicate, message, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(.05)
    raise AssertionError(message)

def run():
    assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
    assert os.environ.get('YUE_DESKTOP_RECOVERY') == '0'
    profile = WORK / 'profile'
    if profile.exists():
        shutil.rmtree(profile)
    (profile / 'records').mkdir(parents=True)
    for source, target in [('assets/shovey/sprites', 'classic/sprites'),
                           ('assets/shovey-landscape/sprites', 'classic/sprites-landscape')]:
        shutil.copytree(ROOT / source, profile / 'assets/shovey-editor' / target)
    blank = ''.join('0c' if x in (0, 11) or y in (0, 19) else
                    '0a' if (x, y) == (6, 4) else '07' if (x, y) == (6, 15) else '00'
                    for y in range(20) for x in range(12))
    def state():
        p = profile / 'state.txt'
        return p.read_text().split() if p.exists() else []
    def board():
        p = profile / 'board.hex'
        return p.read_text() if p.exists() else ''
    saved = ''
    # Restart the host against only this test's records to prove own-draft recovery.
    for turn in range(2):
        driver_dir = WORK / f'driver-{turn}'
        driver_dir.mkdir(exist_ok=True)
        for name in ('command', 'reply'):
            (driver_dir / name).unlink(missing_ok=True)
        environment = os.environ | {'KRYON_TEST_DRIVER': str(driver_dir), 'SDL_VIDEODRIVER': 'x11'}
        with (WORK / f'public-ui-{turn}.log').open('w') as log:
            child = subprocess.Popen([WORK / 'public-editor-ui-test'], cwd=profile,
                                     env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                window = wait(lambda: subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                    capture_output=True, text=True).stdout.split(), 'No public editor private window')[0]
                assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                driver = EditorUiDriver(driver_dir, child, window)
                wait(lambda: len(state()) == 3, 'Editor did not initialize')
                assert board() == blank, 'Public entry prefilled a campaign board'
                assert state()[:2] == ['0', str(turn)], state()
                # The editor starts on its choice of edition, Classic first.
                wait(lambda: any(n.get('key') == 110 for n in driver.nodes()), 'Public editor start did not render')
                time.sleep(.25)
                shot = WORK / f'public-blank-{turn}.png'
                subprocess.run(['import', '-window', window, str(shot)], check=True)
                with Image.open(shot).convert('RGB') as pixels:
                    assert sum(high - low for low, high in pixels.getextrema()) > 120, 'Public editor window did not paint'
                driver.press('Levels')
                nodes = driver.nodes()
                (WORK / f'levels-tree-{turn}.json').write_text(json.dumps(nodes, indent=2))
                assert not any(260000 <= n.get('key', 0) < 270000 for n in nodes), 'Campaign action remains accessible'
                assert not any('Story' in n.get('label', '') or '/levels/' in n.get('label', '') for n in nodes)
                assert any(n.get('label') == 'New level' for n in nodes)
                if turn:
                    driver.press('Level 1')
                    wait(lambda: state()[:1] == ['1'], 'Saved own draft did not reopen')
                    assert board() == saved, 'Saved own draft changed after restarting'
                    driver.press('Levels')
                    driver.press('New level')
                    wait(lambda: any(n.get('key') == 110 for n in driver.nodes()), 'New level did not open the start')
                    driver.press('Classic')
                    wait(lambda: state()[:2] == ['2', '2'], 'New level did not save')
                    assert board() == blank, 'New level copied an existing board'
                    print('Public editor: blank creation, own-level list, save/reopen and fake publication passed')
                    continue
                driver.press('New level')
                wait(lambda: any(n.get('key') == 110 for n in driver.nodes()), 'New level did not open the start')
                driver.press('Classic')
                wait(lambda: state()[:2] == ['1', '1'], 'New level did not save')
                assert board() == blank
                # Paint through the real board control, then wait for its solver proof.
                nodes = driver.nodes()
                area = next(n for n in nodes if n.get('label') == 'Board: tap or drag to paint' and n.get('visible'))
                # Board geometry is also exposed by the image grid: at this size
                # the editor uses the 12x20 portrait orientation.
                x = area['visible_x'] + area['visible_width'] * .5
                y = area['visible_y'] + area['visible_height'] * .5
                subprocess.run(['xdotool', 'mousemove', '--window', window, str(int(x)), str(int(y)), 'mousedown', '1'], check=True)
                time.sleep(.1)
                subprocess.run(['xdotool', 'mouseup', '1'], check=True)
                wait(lambda: board() != blank, 'Painting did not change authored board')
                wait(lambda: len(state()) == 3 and state()[2] == '3', 'Authored board did not receive solver proof', seconds=60)
                saved = board()
                driver.press('Levels')
                driver.press('Publish')
                wait(lambda: any(n.get('key') == 603 for n in driver.nodes()), 'Publish page did not open')
                member = wait(lambda: next((n for n in driver.nodes() if n.get('label') == 'Level 1' and n.get('kind') == 'button'), None), 'Proven authored level missing from publication')
                if not member.get('selected'):
                    driver.press('Level 1')
                driver.press('Publish')
                (WORK / 'publish-tree.json').write_text(json.dumps(driver.nodes(), indent=2))
                callback = profile / 'fake-publish.json'
                wait(callback.exists, 'Publish did not reach the fake callback')
                request = json.loads(callback.read_text())
                assert request.get('operation') == 'publish', request
                assert 'document' in request, request
                wait(lambda: any(n.get('label') == 'Published.' for n in driver.nodes()), 'Fake publish response did not reach UI')
                assert list((profile / 'records').iterdir()), 'No own records saved'
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)
