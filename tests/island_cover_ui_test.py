"""Covers run Classic, Island, Editor; Island stays locked; the Editor opens
its Classic levels page and a new board. Private Xvfb and a disposable profile;
no account is signed in and nothing is bought."""
import argparse
import contextlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from PIL import Image, ImageChops, ImageStat
from world_map_test_support import start_map_destination

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--driver-source', type=Path, required=True)
a = p.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
assert os.environ['YUE_DESKTOP_RECOVERY'] == '0'
root = Path(__file__).resolve().parents[1]
out = root / 'work/island-cover-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(out)], cwd=root, check=True)
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(a.driver_source.resolve() / 'tests'))
from ui_driver import UiDriver

# The public card is present even where Island's source is private.
island = True
DURATION = re.compile(r'\b(day|days|week|weeks|month|months|year|years|hour|hours|until|ends?|limited)\b', re.I)


with tempfile.TemporaryDirectory(dir=out, prefix='guest-') as folder:
    profile = Path(folder)
    player = profile / 'games/arcade.shovey-player/records'
    player.mkdir(parents=True)
    (player / 'level-updates').write_text('off')
    classic = profile / 'games/arcade.shovey/records/local.campaign'
    driver = UiDriver(profile / 'driver')
    log_path = out / 'native.log'

    @contextlib.contextmanager
    def application():
        driver.reset()
        with log_path.open('a') as log:
            child = subprocess.Popen([str(a.binary.resolve())], cwd=a.binary.resolve().parent,
                env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile), 'LANG': 'en_US.UTF-8'},
                stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, log_path)
            try:
                yield child
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)

    def cover(child, name):
        """The whole window of the selected cover, once it has settled."""
        window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0]
        driver.wait_idle(frames=5, timeout=10)
        shot = out / (name + '.png')
        subprocess.run(['import', '-window', window, str(shot)], check=True)
        with Image.open(shot) as image:
            return image.convert('RGB').resize((96, 96))

    def different(first, second, what):
        assert max(ImageStat.Stat(ImageChops.difference(first, second)).mean) > 5, what

    with application() as child:
        driver.wait(label='Play', role='button', timeout=60)
        classic_cover = cover(child, 'classic')
        if island:
            driver.press(label='Next', role='button')
            driver.wait(contains='40% off', visible=True)
            island_cover = cover(child, 'island')
            different(classic_cover, island_cover, 'Island shares the Classic cover')
            text = driver.text()
            assert '51' in text, text
            assert not DURATION.search(text), ('Island must never state a duration', text)

            # A guest who has not bought Island sees the locked offer.
            # The cover's one action reads Unlock and the price; only the offer stays as its caption.
            assert not driver.find(contains='51 Dew · ', visible=True), 'The cover kept a separate price'
            driver.press(label='Unlock · 51 Dew', role='button')
            # Guests sign in first; the one action carries Unlock and the price.
            action = driver.wait(key=49530, role='button')
            driver.wait(key=49544)
            assert action['label'] == 'Unlock · 51 Dew', action
            for key in (49540, 49541, 49542):
                assert not driver.find(key=key), ('A separate price label remains', key)
            text = driver.text()
            assert text.count('51 Dew') == 1 and '85 Dew' not in text, ('The price shows apart from Unlock', text)
            assert '40% off' in text, text
            assert not DURATION.search(text), ('The offer must never state a duration', text)
            # A purchase control needs a fresh quote.
            assert not driver.find(key=49534) and not driver.find(key=49532), 'A guest was offered a purchase'
            assert not list(player.glob('island*')), 'A guest wrote an Island entitlement'
            driver.press(key=49512, role='button')
            driver.wait(contains='40% off', visible=True)
            driver.wait_gone(key=49530)
            assert driver.find(label='Unlock · 51 Dew', role='button', visible=True), 'Back left the Island cover'
            assert not driver.find(contains='Level 1 / ', visible=True), 'Back opened the locked game'
        driver.press(label='Next', role='button')
        driver.wait(label='Editor', role='image', visible=True)
        driver.wait(label='Open', role='button')
        editor_cover = cover(child, 'editor')
        different(classic_cover, editor_cover, 'Editor shares the Classic cover')
        if island:
            different(island_cover, editor_cover, 'Editor shares the Island cover')
        # The carousel wraps past Classic, in the same order.
        driver.press(label='Previous', role='button')
        if island:
            driver.wait(contains='40% off', visible=True)
            driver.press(label='Previous', role='button')
        driver.wait(label='Play', role='button')

        # Play Classic for one saved move.
        driver.press(label='Play', role='button')
        start_map_destination(driver, 1)
        driver.wait(contains='Level 1 / ', role='text', timeout=30)
        with contextlib.suppress(AssertionError):
            driver.press(label='Swipe and tap', timeout=5)
            driver.press(label='Got it', role='button', timeout=5)
        deadline = time.monotonic() + 20
        while not classic.exists() and time.monotonic() < deadline:
            for key in ('up', 'left', 'down', 'right'):
                driver.key(key)
            time.sleep(.1)
        assert classic.exists(), 'Classic saved no device record'
        driver.press(label='Back', role='button')
        driver.wait(label='Play', role='button')

    with application() as child:
        driver.wait(label='Play', role='button', timeout=60)
        driver.press(label='Next', role='button')
        if island:
            driver.wait(contains='40% off', visible=True)
            driver.press(label='Next', role='button')
        driver.press(label='Open', role='button')
        driver.wait(label='New level', role='text', timeout=30)
        driver.press(label='Levels', role='button')
        # Levels lists the creator's own boards under Classic; story levels
        # are no longer editor starting points.
        driver.wait(label='Classic', role='text')
        driver.wait(label='Your levels', role='text')
        assert not any(260000 <= node.get('key', 0) < 264000 for node in driver.tree()), 'Story levels returned to the editor'
        driver.press(label='New level', role='button')
        driver.wait(key=200000, timeout=20)
        driver.wait(label='Play', role='button')
        driver.key('escape')
        driver.wait(label='Open', role='button')

with log_path.open(errors='replace') as log:
    for line in log:
        assert 'host capability' not in line, line[:1000]
order = 'Classic, Island, Editor'
offer = 'Island locked for a guest at 51 Dew, 85 struck, 40% off, no duration; ' if island else ''
print(f'PASS: covers {order}; {offer}'
      'Editor opened its Classic levels page and a new board with no host capability failure.')
