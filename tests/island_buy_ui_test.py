"""The localized Buy cover opens the locked offer in the production player."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
args = parser.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
root = Path(__file__).resolve().parents[1]
work = root / 'work/island-buy-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=root, check=True)
work.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(args.driver_source.resolve()))
from ui_driver import UiDriver
for language, play, next_label, buy in [('en_US.UTF-8', 'Play', 'Next', 'Buy'), ('de_DE.UTF-8', 'Spielen', 'Weiter', 'Kaufen')]:
    with tempfile.TemporaryDirectory(dir=work, prefix='guest-') as directory:
        profile = Path(directory)
        records = profile / 'games/arcade.shovey-player/records'
        records.mkdir(parents=True)
        (records / 'level-updates').write_text('off')
        driver = UiDriver(profile / 'driver')
        log_path = work / (language + '.log')
        with log_path.open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile), 'XDG_DATA_HOME': str(profile / 'xdg'), 'LANG': language},
                stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                driver.wait(label=play, role='button', timeout=60)
                driver.press(label=next_label, role='button')
                driver.wait(label=buy, role='button')
                driver.press(label=buy, role='button')
                driver.wait(key=49540)
                driver.wait(key=49530, role='button')
                assert not driver.find(key=49534) and not driver.find(key=49532)
                driver.press(key=49512, role='button')
                driver.wait(label=buy, role='button')
                assert not driver.find(key=4, role='text'), 'Opening Buy left an action failure on the cover'
                assert not list(records.glob('island*'))
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)
print('Island Buy local UI tests: English/German action dispatch, guest lock and Back passed')
