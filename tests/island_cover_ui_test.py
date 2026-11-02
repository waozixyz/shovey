"""Covers run Classic, Island, Editor; Island stays locked; the Editor opens
unlocked levels with working previews. Private Xvfb and a disposable profile;
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
UNLOCKED = 12
DURATION = re.compile(r'\b(day|days|week|weeks|month|months|year|years|hour|hours|until|ends?|limited)\b', re.I)


def campaign(path):
    """Raise a real saved game to UNLOCKED levels, keeping its board."""
    text = path.read_text()
    assert text[:2] == 'C2', text[:2]
    marks = ''.join('1' if level + 1 < UNLOCKED else '0' for level in range(175))
    path.write_text(f'C2{UNLOCKED:02x}{marks}{text[4 + 175:]}')


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
            driver.press(label='Open', role='button')
            driver.wait(key=49540)
            price = driver.wait(key=49540)
            was = driver.wait(key=49541)
            strike = driver.wait(key=49542)
            driver.wait(key=49544)
            assert price['label'] == '51 Dew', price
            assert was['label'] == '85 Dew', was
            assert was['x'] <= strike['x'] and strike['x'] + strike['width'] <= was['x'] + was['width'] + 1, (was, strike)
            assert was['y'] < strike['y'] < was['y'] + was['height'], (was, strike)
            text = driver.text()
            assert '40% off' in text, text
            assert not DURATION.search(text), ('The offer must never state a duration', text)
            # Guests sign in first; a purchase control needs a fresh quote.
            driver.wait(key=49530, role='button')
            assert not driver.find(key=49534) and not driver.find(key=49532), 'A guest was offered a purchase'
            assert not list(player.glob('island*')), 'A guest wrote an Island entitlement'
            driver.press(key=49512, role='button')
            driver.wait(contains='40% off', visible=True)
            driver.wait_gone(key=49540)
            assert driver.find(label='Open', role='button', visible=True), 'Back left the Island cover'
            assert not driver.find(contains='Level 1 / ', visible=True), 'Back opened the locked game'
        driver.press(label='Next', role='button')
        driver.wait(contains='Shovey Editor', visible=True)
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

        # Play Classic for one saved move: a real record to raise.
        driver.press(label='Play', role='button')
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

    campaign(classic)
    with application() as child:
        driver.wait(label='Play', role='button', timeout=60)
        driver.press(label='Next', role='button')
        if island:
            driver.wait(contains='40% off', visible=True)
            driver.press(label='Next', role='button')
        driver.press(label='Open', role='button')
        driver.wait(label='New level', role='text', timeout=30)
        driver.press(label='Levels', role='button')
        driver.wait(label='Story levels', role='text')
        driver.wait(label='1', role='image')
        # The list reads Classic's device save on its first poll, and draws
        # only the rows in view: scroll to a level's row to see it.
        def row(number):
            screen = driver.tree()[0]
            for _ in range(120):
                nodes = driver.find(key=260000 + number * 4, visible=True)
                middle = nodes[0]['y'] + nodes[0]['height'] / 2 if nodes else screen['height']
                if 140 < middle < screen['height'] - 120:
                    return
                driver.pointer(screen['width'] / 2, screen['height'] / 2, wheel=-2 if middle > 140 else 2)
                driver.wait_idle(frames=2)
            raise AssertionError(('Level never scrolled into view', number))
        row(UNLOCKED)
        deadline = time.monotonic() + 15
        while not driver.find(key=260000 + UNLOCKED * 4 + 1, role='image', visible=True) and time.monotonic() < deadline:
            time.sleep(.1)
        preview = driver.find(key=260000 + UNLOCKED * 4 + 1, role='image', visible=True)
        assert preview and preview[0]['label'] == str(UNLOCKED), ('Unlocked level lacks its preview', UNLOCKED, preview)
        row(UNLOCKED + 1)
        assert driver.find(key=260000 + (UNLOCKED + 1) * 4 + 3, visible=True), 'The next level is not locked'
        assert not driver.find(key=260000 + (UNLOCKED + 1) * 4 + 1, visible=True), 'A locked level shows its board'
        # An unlocked level other than the first opens for editing.
        row(UNLOCKED)
        driver.press(key=260000 + UNLOCKED * 4)
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
      f'Editor opened unlocked story level {UNLOCKED} with previews and no host capability failure.')
