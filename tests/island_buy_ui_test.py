"""One press on the localized Unlock-and-price cover action unlocks in the production player, with no
panel in between: a guest is taken to sign in, and nothing is bought or written."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from world_map_test_support import private_environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
args = parser.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
root = Path(__file__).resolve().parents[1]
work = root / 'build/tests/island-buy-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=root, check=True)
work.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
from ui_driver import UiDriver
for language, play, next_label, unlock in [('en_US.UTF-8', 'Play', 'Next', 'Unlock'),
        ('de_DE.UTF-8', 'Spielen', 'Weiter', 'Freischalten')]:
    # A guest has no quote yet, so the launch price is what both actions show.
    buy = unlock + ' · 51 Dew'
    with tempfile.TemporaryDirectory(dir=work, prefix='guest-') as directory:
        profile = Path(directory)
        records = profile / 'games/arcade.shovey-player/records'
        records.mkdir(parents=True)
        (records / 'level-updates').write_text('off')
        driver = UiDriver(profile / 'driver')
        log_path = work / (language + '.log')
        with log_path.open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()) | {'LANG': language},
                stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                driver.wait(label=play, role='button', timeout=60)
                driver.press(label=next_label, role='button')
                driver.wait(label=buy, role='button')
                windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
                assert len(windows) == 1
                window = windows[0]
                for width, height in ((320, 720), (960, 600)):
                    subprocess.run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)], check=True)
                    driver.wait_idle(frames=8)
                    button = driver.wait(label=buy, role='button')
                    offers = driver.find(contains='40', role='text', visible=True)
                    assert len(offers) == 1, offers
                    ribbon = offers[0]
                    assert button['y'] - 24 <= ribbon['y'] < button['y'], (button, ribbon)
                    assert ribbon['y'] + ribbon['height'] > button['y'], (button, ribbon)
                    assert ribbon['x'] >= button['x'] and ribbon['x'] + ribbon['width'] <= button['x'] + button['width'], (button, ribbon)
                    subprocess.run(['import', '-window', window, str(work / f'{language}-ribbon-{width}.png')], check=True)
                cover_key = button['key']
                driver.press(label=buy, role='button')
                # One press and no panel: a guest lands on the Profile's sign-in card.
                driver.wait(key=701, timeout=30)
                assert not any(driver.find(key=key) for key in (49510, 49511, 49512, 49520, 49530, 49532, 49534, 49536)), \
                    'The unlock panel is back'
                subprocess.run(['import', '-window', window, str(work / f'{language}-sign-in.png')], check=True)
                driver.key('escape')
                # The cover is where it was, still locked at the same price.
                again = driver.wait(label=buy, role='button')
                assert again['key'] == cover_key, 'Existing Island cover changed during unlock'
                assert not driver.find(key=4, role='text'), 'Pressing Unlock left an action failure on the cover'
                assert not list(records.glob('island*'))
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)
print('Island Unlock local UI tests: English/German one-press action, guest sign-in, no panel and no entitlement passed')
