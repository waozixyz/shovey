"""Exercise the actual game/chest dialog only on a disposable private display."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--preview', type=Path, required=True)
preview = parser.parse_args().preview.resolve()
output = ROOT / 'build/treasure-preview-ui'
output.mkdir(parents=True, exist_ok=True)


def wait(predicate, message):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        if result := predicate():
            return result
        time.sleep(.04)
    raise AssertionError(message)


with tempfile.TemporaryDirectory(dir=output, prefix='profile-') as temporary:
    profile = Path(temporary)
    env = {key: value for key, value in os.environ.items()
           if key not in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS',
                          'SESSION_MANAGER', 'GDK_DISPLAY', 'KRYON_TEST_DRIVER')}
    env.update(KRYON_APP_DATA=str(profile), SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
    def document(name):
        for path in profile.rglob(name):
            if path.is_file():
                return json.loads(path.read_text())
        return None
    with (output / 'game.log').open('w') as log:
        child = subprocess.Popen([str(preview / 'player')], cwd=preview, env=env,
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            def windows():
                assert child.poll() is None, 'Actual game exited before rendering'
                return subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                      capture_output=True, text=True).stdout.split()
            window = wait(windows, 'No private game window')[0]
            started = wait(lambda: document('preview.started'), 'The actual game entry did not run')
            assert started['level'] == 1003 and started['unsigned']
            subprocess.run(['xdotool', 'windowsize', window, '1280', '800', 'windowfocus', window], check=True)
            time.sleep(.5)
            # A previously discovered room must still be absent from the
            # player selector. The preview seeds the actual discovery record.
            subprocess.run(['xdotool', 'mousemove', '--window', window, '30', '26', 'mousedown', '1'], check=True)
            time.sleep(.12)
            subprocess.run(['xdotool', 'mouseup', '1'], check=True)
            time.sleep(.5)
            selector = output / 'player-selector.png'
            subprocess.run(['import', '-window', window, str(selector)], check=True)
            labels = subprocess.check_output(['tesseract', str(selector), 'stdout', '--psm', '11'],
                                             stderr=subprocess.DEVNULL, text=True)
            assert re.search(r'\b29\b', labels) and re.search(r'\b30\b', labels), labels
            assert not re.search(r'\b(?:29a|175[ab])\b', labels, re.IGNORECASE), labels
            subprocess.run(['xdotool', 'mousemove', '--window', window, '1205', '32', 'mousedown', '1'], check=True)
            time.sleep(.12)
            subprocess.run(['xdotool', 'mouseup', '1'], check=True)
            time.sleep(.25)
            subprocess.run(['import', '-window', window, str(output / 'room.png')], check=True)
            # The real engine's bridge/chest route, transformed to landscape
            # screen directions; no reward state or UI dialog is fabricated.
            for key in ('Down', 'Right', *(['Down'] * 6)):
                subprocess.run(['xdotool', 'key', '--window', window, key], check=True)
                time.sleep(.2)
            result = wait(lambda: document('preview.treasure'), 'The real chest did not trigger its dialog')
            assert result == dict(level=1003, cell=124, dialog='signin', credited=False)
            time.sleep(.3)
            screenshot = output / 'treasure-dialog.png'
            subprocess.run(['import', '-window', window, str(screenshot)], check=True)
            text = subprocess.check_output(['tesseract', str(screenshot), 'stdout'], stderr=subprocess.DEVNULL, text=True)
            assert 'secret chest' in text.lower() and 'Connect an account' in text, text
            # Activate the real reward card action, then verify the actual
            # Entity account composition and modal dismissal preserve the game.
            def click(x, y):
                subprocess.run(['xdotool', 'mousemove', '--window', window, str(x), str(y), 'mousedown', '1'], check=True)
                time.sleep(.12)
                subprocess.run(['xdotool', 'mouseup', '1'], check=True)
                time.sleep(.3)
            click(590, 752)
            account = wait(lambda: document('preview.account-modal'), 'Connect account did not open its modal')
            assert account == dict(service='entity.profile', modal='account', offline=True, credited=False)
            modal_image = output / 'account-modal.png'
            subprocess.run(['import', '-window', window, str(modal_image)], check=True)
            modal_ocr = output / 'account-modal-ocr.png'
            subprocess.run(['convert', str(modal_image), '-crop', '560x300+360+250', '-resize', '300%', str(modal_ocr)], check=True)
            modal_text = subprocess.check_output(['tesseract', str(modal_ocr), 'stdout', '--psm', '6'], stderr=subprocess.DEVNULL, text=True)
            assert 'Account' in modal_text and 'Not signed in' in modal_text and 'offline preview' in modal_text, modal_text
            subprocess.run(['xdotool', 'key', '--window', window, 'Down'], check=True)
            time.sleep(.25)
            click(890, 280)
            closed = wait(lambda: document('preview.account-closed'), 'Account modal did not dismiss')
            assert closed == dict(preserved=True), 'Account modal moved or reset the player'
            (output / 'result.json').write_text(json.dumps(dict(started=started, treasure=result,
                actual_game_pid=child.pid, preview=str(preview), screenshot=str(screenshot),
                account_files_copied=False, live_claim=False, account_modal=account, account_closed=closed), indent=2) + '\n')
            print('Actual game preview: level29a rendered; eight real moves reach chest; unsigned account dialog and Connect account modal opened/closed with board preserved; no credit/live claim', flush=True)
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
