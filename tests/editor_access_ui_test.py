"""The Editor opens from its cover for everyone, signed out or signed in, and
offers only the creator's own levels, never campaign levels. Its Shovey Island
row reads Unlock and the price while Island is locked and opens the unlock
page, never Island's editor. Escape in a level returns to the world map, and
the map's Escape returns to the title.

Private Xvfb and disposable profiles; the signed-in one holds an offline test
account key. No node, wallet or purchase is used, and the owner's profile is
never read."""
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
# 210 is the Shovey Island row.
LEVELS_PAGE = {200, 202, 120, 121, 203, 205, 210}


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


def open_editor(driver, who):
    action = driver.wait(label='Open', role='button')
    assert action['enabled'], (f'The Editor is disabled for a {who} player', action)
    driver.press(label='Open', role='button')
    driver.wait(label='New level', role='text', timeout=30)


def locked_island_row(driver, who):
    """Locked, the Island row shows Unlock and its price and opens the unlock
    page; Back there returns to the Editor's levels."""
    row = driver.wait(key=210, role='button')
    shown = ' '.join(str(row.get(field, '')) for field in ('label', 'detail', 'description', 'value'))
    assert 'Shovey Island' in shown and 'Unlock · ' in shown, (f'Locked Island row for a {who} player', row)
    driver.press(key=210, role='button')
    # 49530 buys; offline the page shows the waiting 49534 action instead.
    driver.wait(key=49512, role='button', timeout=30)
    actions = driver.find(key=49530, role='button') + driver.find(key=49534, role='button')
    assert actions and 'Unlock' in actions[0].get('label', ''), actions
    assert not driver.find(key=600000), 'A locked Island opened its editor'
    driver.press(key=49512, role='button')
    driver.wait(key=210, role='button')
    driver.wait(label='Your levels', role='text')


def only_own_levels(driver, who):
    """Levels lists the creator's own boards and New level; no campaign level
    can be opened from it."""
    driver.press(label='Levels', role='button')
    driver.wait(label='Classic', role='text')
    driver.wait(label='Your levels', role='text')
    nodes = driver.tree()
    assert not driver.find(label='Story levels'), who
    assert not any(260000 <= node.get('key', 0) < 264000 for node in nodes), (f'Campaign levels offered to a {who} player')
    buttons = [node for node in nodes if node.get('kind') == 'button' and node.get('visible')]
    others = [node.get('label') for node in buttons if node.get('key') not in LEVELS_PAGE and node.get('key') not in OWN_LEVELS]
    assert not others, (f'The Levels page offers more than own levels to a {who} player', others)
    locked_island_row(driver, who)
    driver.press(label='New level', role='button')
    driver.wait(key=200000, timeout=20)
    driver.wait(label='Play', role='button')


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
            only_own_levels(driver, who)
            driver.key('escape')
            # It stays available and opens again after returning to the title.
            open_editor(driver, who)
            driver.key('escape')
            driver.wait(label='Open', role='button')

            if owner:
                # Escape in a level opens the world map; Escape on the map leaves for the title.
                driver.press(label='Previous', role='button')
                driver.press(label='Previous', role='button')
                driver.press(label='Play', role='button')
                start_map_destination(driver, 1)
                driver.wait(contains='Level 1 / ', role='text', timeout=30)
                dismiss_level_prompts(driver)
                driver.key('escape')
                assert_fullscreen_map(driver)
                assert not driver.find(contains='Level 1 / ', visible=True), 'Escape left the level on screen'
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
print(f'Editor access local UI test passed: {" and ".join(results)} players open the Editor twice with only '
      'their own levels, the locked Island row opens its unlock page; Escape goes level → map → title')
