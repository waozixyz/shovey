"""Open the real Book on a private display, using disposable found/hidden saves."""
import argparse
import contextlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image, ImageStat

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--driver-source', type=Path, required=True)
a = p.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
root = Path(__file__).resolve().parents[1]
out = root / 'work/collectible-book-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(out)], cwd=root, check=True)
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(a.driver_source / 'tests'))
from ui_driver import UiDriver

with tempfile.TemporaryDirectory(dir=out, prefix='guest-') as folder:
    profile = Path(folder)
    records = profile / 'games/arcade.shovey/records'
    records.mkdir(parents=True)
    (records / 'collectibles.v1.guest').write_text('1' + '0' * 63)
    player = profile / 'games/arcade.shovey-player/records'
    player.mkdir(parents=True)
    (player / 'level-updates').write_text('off')
    driver = UiDriver(profile / 'driver')

    @contextlib.contextmanager
    def application(name):
        driver.reset()
        log_path = out / (name + '.log')
        with log_path.open('w') as log:
            child = subprocess.Popen([str(a.binary.resolve())], cwd=a.binary.resolve().parent,
                env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile),
                    'ENTITY_DATA': str(profile / 'entity'), 'LANG': 'en_US.UTF-8', 'SDL_AUDIODRIVER': 'dummy'},
                stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                driver.wait(label='Play', role='button', timeout=60)
                icon = driver.wait(key=49209, role='image')
                driver.wait_idle(frames=5, timeout=10)
                window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0]
                title = out / (name + '-title.png')
                subprocess.run(['import', '-window', window, str(title)], check=True)
                viewport = driver.tree()[0]
                with Image.open(title) as image:
                    sx = image.width / viewport['visible_width']
                    sy = image.height / viewport['visible_height']
                    x = (icon['visible_x'] - viewport['visible_x']) * sx
                    y = (icon['visible_y'] - viewport['visible_y']) * sy
                    crop = image.convert('RGB').crop((round(x), round(y), round(x + icon['visible_width'] * sx), round(y + icon['visible_height'] * sy)))
                    assert max(ImageStat.Stat(crop).stddev) > 8, 'Book cover icon did not render'
                driver.press(key=49208, role='button')
                driver.wait(label='Collectible Book', role='text', timeout=60)
                driver.wait(label='1 / 16', role='text')
                driver.wait(label='Lucky pebble', role='text')
                driver.wait(label='Still hidden', role='text')
                driver.wait(label='A little luck for the road.', role='text')
                yield child
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)

    with application('first') as child:
        driver.wait_idle(frames=5, timeout=10)
        windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
        assert len(windows) == 1
        shot = out / 'book.png'
        subprocess.run(['import', '-window', windows[0], str(shot)], check=True)
        with Image.open(shot) as image:
            assert max(ImageStat.Stat(image.convert('RGB')).stddev) > 10
        driver.press(key=64001, role='button')
        driver.wait(label='Play', role='button')
        driver.wait(key=49208, role='button')
    with application('reopened'):
        assert (records / 'collectibles.v1.guest').read_text() == '1' + '0' * 63
print('PASS: real Book shows found art, name, flavour and hidden silhouettes; Back returns to cover; finds survive restart.')
