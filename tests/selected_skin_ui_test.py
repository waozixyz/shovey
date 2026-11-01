"""Verify title PFP changes with a saved wardrobe choice, on private Xvfb only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image, ImageChops, ImageStat

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--driver-source', type=Path, required=True)
a = p.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
root = Path(__file__).resolve().parents[1]
out = root / 'work/selected-skin-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(out)], cwd=root, check=True)
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(a.driver_source.resolve()))
from ui_driver import UiDriver

with tempfile.TemporaryDirectory(dir=out, prefix='guest-') as folder:
    profile = Path(folder)
    records = profile / 'games/arcade.shovey/records'
    records.mkdir(parents=True)
    (records / 'shop.v1.guest').write_text(json.dumps(dict(version=1, owner='', selected=1, owned=6, spent=300)))
    player = profile / 'games/arcade.shovey-player/records'
    player.mkdir(parents=True)
    (player / 'level-updates').write_text('off')
    driver = UiDriver(profile / 'driver')
    log_path = out / 'native.log'
    with log_path.open('w') as log:
        child = subprocess.Popen([str(a.binary.resolve())], cwd=a.binary.resolve().parent,
            env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile), 'LANG': 'en_US.UTF-8'},
            stdout=log, stderr=subprocess.STDOUT)
        driver.attach(child, log_path)
        try:
            driver.wait(label='Play', role='button', timeout=60)
            windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
            assert len(windows) == 1
            window = windows[0]
            subprocess.run(['xdotool', 'windowsize', '--sync', window, '900', '800'], check=True)
            def picture(name):
                button = driver.wait(key=49204, role='button')
                driver.wait_idle(frames=5, timeout=10)
                shot = out / (name + '.png')
                subprocess.run(['import', '-window', window, str(shot)], check=True)
                with Image.open(shot) as image:
                    x, y = int(button['x']), int(button['y'])
                    return image.convert('RGB').crop((x, y, x + int(button['width']), y + int(button['height'])))
            first = picture('ember')
            driver.press(key=49200, role='button')
            driver.wait(key=62046, role='button', timeout=30)
            driver.press(key=62046, role='button')
            driver.press(key=61101, role='button')
            second = picture('frost')
            difference = ImageStat.Stat(ImageChops.difference(first, second)).mean
            assert max(difference) > 5, ('Selected skin did not change title PFP', difference)
            saved = json.loads((records / 'shop.v1.guest').read_text())
            assert saved['selected'] == 2
            driver.press(key=49204, role='button')
            driver.key('escape')
            driver.wait(key=49204, role='button')
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
print('PASS: saved Ember title PFP changes immediately to Frost after wardrobe selection; Profile still opens.')
