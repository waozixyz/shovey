"""The Editor opens from its cover for everyone, signed out or signed in, on
its start: big Classic and Shovey Island cards to begin a new level. Classic
always makes a new level and opens it; Back returns to the start. The cards
are the editions' title banners. While Island is locked its card carries
Unlock and the price, and one press on it never opens Island's editor
without an unlock: signed out it leads to sign in, and an account that
cannot reach its node stays in the Editor. Levels holds only the creator's own levels,
never campaign levels, with New level leading back to the start. Escape in a
level returns to the world map, and the map's Escape returns to the title.

Private Xvfb and disposable profiles; the signed-in one holds an offline test
account key. No node, wallet or purchase is used, and the owner's profile is
never read. The owned Island path is tested in island_delivery_test.py."""
import argparse
import contextlib
import hashlib
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from world_map_test_support import assert_fullscreen_map, private_environment, start_map_destination
from shovey_standalone_ui_test import answer_cover_question

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
work = root / 'work/editor-access-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=root, check=True)
sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
from ui_driver import UiDriver

# The editor's own catalog buttons; story levels used 260000 and up.
OWN_LEVELS = range(240000, 250000)
# Back, Publish, Explore, Export, the list, New level and the Island row.
LEVELS_PAGE = {200, 202, 120, 121, 203, 205, 210}
# Back, the Classic and Island cards, Island's Unlock action and Levels.
START_PAGE = {100, 110, 130, 133, 122}


def offline_account(folder):
    """A fresh plain account key Entity accepts offline: its public ID is the
    digest of its public key. It signs nothing and never reaches a node."""
    public = secrets.token_bytes(1312)
    owner = hashlib.sha256(public).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    key = folder / 'account.key'
    key.write_text(f'public_id={owner}\npublic_key={public.hex()}\nprivate_key={secrets.token_bytes(2560).hex()}\n')
    key.chmod(0o600)
    return owner


def dismiss_level_prompts(driver):
    """The first level asks how to move, then Pip explains it."""
    with contextlib.suppress(AssertionError):
        driver.press(label='Swipe and tap', timeout=5)
    deadline = time.monotonic() + 10
    while driver.find(label='Got it', role='button', visible=True) and time.monotonic() < deadline:
        driver.press(label='Got it', role='button')
        driver.wait_idle(frames=3)


def shown(node):
    return ' '.join(str(node.get(field, '')) for field in ('label', 'detail', 'description', 'value'))


def start_page(driver, who):
    """The start offers exactly the two editions as big cards, Island locked."""
    driver.wait(label='New level', role='text', timeout=30)
    classic = driver.wait(key=110, role='button')
    island = driver.wait(key=130, role='button')
    assert 'Classic' in shown(classic), (who, classic)
    assert 'Shovey Island' in shown(island) and 'Unlock · ' in shown(island), (f'Locked Island card for a {who} player', island)
    tag = driver.wait(key=133, role='button')
    assert tag.get('label', '').startswith('Unlock · '), tag
    for card in (classic, island):
        assert card['width'] >= 200 and card['height'] >= 200, ('The start cards are not big', who, card)
    # Each card is its title banner: the cover art and the logo over it.
    for art in (111, 131):
        assert 'title/shovey-' in str(driver.find(key=art)), ('A start card lacks its title banner', art)
    assert driver.find(key=112) and driver.find(key=132), 'A start card lacks its logo'
    buttons = [node for node in driver.tree() if node.get('kind') == 'button' and node.get('visible')]
    others = [node.get('label') for node in buttons if node.get('key') not in START_PAGE]
    assert not others, (f'The start offers more than its two editions to a {who} player', others)


def locked_island(driver, who, key):
    """Locked, one press on Island shows no panel and opens no editor: signed
    out it leads to the Profile's sign-in card; an account that cannot reach
    its node stays in the Editor, which says why."""
    driver.press(key=key, role='button')
    deadline = time.monotonic() + 60
    while True:
        assert not any(driver.find(key=panel) for panel in (49512, 49520, 49530, 49534, 49536)), 'The unlock panel is back'
        assert not driver.find(key=93303), f'A locked Island opened its editor for a {who} player'
        if driver.find(key=701, visible=True):
            driver.key('escape')
            break
        if driver.find(key=138, visible=True):
            break
        assert time.monotonic() < deadline, f'Pressing a locked Island did nothing for a {who} player'
        time.sleep(0.2)
    driver.wait(key=key, role='button')
    assert not driver.find(key=93303), f'A locked Island opened its editor for a {who} player'


def classic_new_level(driver):
    """Classic makes a new level and opens it; Back saves it and returns to the start."""
    driver.press(key=110, role='button')
    driver.wait(key=200000, timeout=20)
    driver.wait(label='Play', role='button')
    driver.key('escape')
    driver.wait(key=110, role='button')
    driver.wait(key=130, role='button')


def only_own_levels(driver, who):
    """Levels lists the creator's own boards with the new Classic level, the
    Island row and New level; no campaign level can be opened from it."""
    driver.press(label='Levels', role='button')
    driver.wait(label='Your levels', role='text')
    driver.wait(label='Classic', role='text')
    nodes = driver.tree()
    assert not driver.find(label='Story levels'), who
    assert not any(260000 <= node.get('key', 0) < 264000 for node in nodes), (f'Campaign levels offered to a {who} player')
    buttons = [node for node in nodes if node.get('kind') == 'button' and node.get('visible')]
    own = [node for node in buttons if node.get('key') in OWN_LEVELS]
    assert len(own) == 1, (f'The new Classic level is missing from Levels for a {who} player', own)
    others = [node.get('label') for node in buttons if node.get('key') not in LEVELS_PAGE and node.get('key') not in OWN_LEVELS]
    assert not others, (f'The Levels page offers more than own levels to a {who} player', others)
    row = driver.wait(key=210, role='button')
    assert 'Shovey Island' in shown(row) and 'Unlock · ' in shown(row), (f'Locked Island row for a {who} player', row)
    locked_island(driver, who, 210)
    driver.wait(label='Your levels', role='text')
    # New level is the start's choice of edition, not another Classic board.
    driver.press(key=205, role='button')
    start_page(driver, who)


def open_editor(driver, who):
    action = driver.wait(label='Open', role='button')
    assert action['enabled'], (f'The Editor is disabled for a {who} player', action)
    driver.press(label='Open', role='button')
    start_page(driver, who)


shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
results = []
for who in ('signed-out', 'signed-in'):
    profile = work / who
    records = profile / 'games/arcade.shovey-player/records'
    records.mkdir(parents=True)
    (records / 'level-updates').write_text('off')
    owner = offline_account(profile / 'entity') if who == 'signed-in' else ''
    driver = UiDriver(profile / 'driver')
    log_path = work / f'{who}.log'
    with log_path.open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
            env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
        driver.attach(child, log_path)
        try:
            answer_cover_question(driver)
            # Profile shows the account's ID when signed in, the sign-in card otherwise.
            driver.press(key=49204, role='button')
            if owner:
                driver.wait(key=1705, timeout=30)
                assert not driver.find(key=701), 'The test account did not sign in'
            else:
                driver.wait(key=701, timeout=30)
            driver.key('escape')
            driver.wait(label='Play', role='button')
            # Let Island's account check settle under this account.
            driver.wait_idle(frames=20, timeout=20)
            driver.press(label='Next', role='button')
            driver.press(label='Next', role='button')
            driver.wait(label='Editor', role='image', visible=True)
            open_editor(driver, who)
            locked_island(driver, who, 130)
            start_page(driver, who)
            classic_new_level(driver)
            only_own_levels(driver, who)
            # Escape on the start leaves the Editor.
            driver.key('escape')
            driver.wait(label='Open', role='button')
            # It stays available and opens again on its start after returning to the title.
            open_editor(driver, who)
            driver.key('escape')
            driver.wait(label='Open', role='button')

            if owner:
                # Escape in a level opens the world map; Escape on the map leaves for the title.
                driver.press(label='Previous', role='button')
                driver.press(label='Previous', role='button')
                driver.press(label='Play', role='button')
                start_map_destination(driver, 1)
                # The level has no counter; its Restart control shows it is open.
                driver.wait(label='Restart', role='button', timeout=30)
                dismiss_level_prompts(driver)
                driver.key('escape')
                assert_fullscreen_map(driver)
                assert not driver.find(label='Restart', role='button', visible=True), 'Escape left the level on screen'
                driver.key('escape')
                driver.wait(label='Play', role='button')
                assert not driver.find(key=20105, visible=True), 'Escape on the map kept the map open'
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
    with log_path.open(errors='replace') as log:
        for line in log:
            assert 'host capability' not in line, line[:1000]
    results.append(who)
print(f'Editor access local UI test passed: {" and ".join(results)} players open the Editor twice on its start '
      'of big Classic and Island title banners; Classic makes a level and Back returns to the start; locked Island shows '
      'Unlock and the price and one press never opens its editor from the start or from Levels, which holds only their own '
      'levels; Escape goes level → map → title')
