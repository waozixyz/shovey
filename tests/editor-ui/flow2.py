"""Disposable private-display check of the Shovey Editor, second pass."""
import os, subprocess, sys, time, json
from pathlib import Path
sys.path.insert(0, '/mnt/storage/Projects/waozixyz/inbe/tests')
from ui_driver import UiDriver
out = Path('/mnt/storage/Projects/waozixyz/shovey/build/ui-test')
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
profile = out / 'profile'
records = profile / 'games/arcade.shovey-editor/records'
driver = UiDriver(out / 'driver')
log = (out / 'flow2.log').open('w')
child = subprocess.Popen([str(out / 'player/shovey')], cwd=str(out / 'player'),
    env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile), 'LANG': 'en_US.UTF-8'}, stdout=log, stderr=subprocess.STDOUT)
driver.attach(child, out / 'flow2.log')
def shot(name):
    time.sleep(0.4)
    subprocess.run(['import', '-window', subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0], str(out / f'{name}.png')], check=False)
def cell_point(board, cell):
    w = board['visible_width'] / 20.0
    return (board['visible_x'] + (cell % 20 + 0.5) * w, board['visible_y'] + (cell // 20 + 0.5) * w)
def tap(board, cell):
    x, y = cell_point(board, cell)
    driver.pointer(x, y); driver.pointer(x, y, down=True); driver.pointer(x, y, down=True); driver.pointer(x, y); driver.release_pointer()
try:
    driver.press(label='Shovey Editor', role='button')
    driver.press(label='Classic', role='button')
    driver.press(label='Level 1')
    driver.wait(contains='Proven winnable')
    driver.press(label='Play')
    driver.key('r')
    driver.wait(label='Testing')
    # Classic: around the crates and home, as the solver's route did.
    for key in ['up'] + ['right'] * 11 + ['down']:
        driver.key(key); time.sleep(0.05)
    driver.wait(contains='Won!', timeout=10)
    shot('play-won')
    index = (records / 'classic-levels').read_text()
    print(index)
    assert 'level 1 0 s 1' in index, 'a win marks the level completed'
    driver.press(label='Edit')
    driver.press(label='Levels')
    # A story level opens as itself; the first stroke makes a copy.
    driver.press(label='3', role='button')
    board = driver.wait(label='Board: tap or drag to paint')
    shot('story-3')
    driver.press(label='Wall', role='button')
    tap(board, 21)
    driver.wait(contains='Saved as a new level', timeout=5)
    index = (records / 'classic-levels').read_text()
    print(index)
    assert ' 3 - 0 - ' in index
    shot('story-copy')
    driver.press(label='Levels')
    driver.press(label='Back')
    driver.press(label='Island', role='button')
    driver.press(label='New level')
    board = driver.wait(label='Board: tap or drag to paint')
    driver.press(label='Sand', role='button')
    a = cell_point(board, 4 * 20 + 15); b = cell_point(board, 4 * 20 + 17)
    driver.drag(a, b, steps=6)
    driver.press(label='Meadow', role='button')
    a = cell_point(board, 5 * 20 + 8); b = cell_point(board, 5 * 20 + 10)
    driver.drag(a, b, steps=6)
    time.sleep(0.5)
    shot('island-edit')
    driver.wait(contains='Proven winnable', timeout=60)
    print((records / 'island-levels').read_text())
    driver.press(label='Levels'); driver.press(label='Publish')
    driver.wait(contains='not available')
    shot('publish')
    driver.press(label='Back'); driver.press(label='Back')
    driver.press(label='Explore')
    driver.wait(contains='not available')
    shot('explore')
    driver.press(label='Back')
    driver.press(label='Export')
    driver.wait(contains='proven levels as text')
    shot('export')
    driver.press(label='Copy')
    time.sleep(0.5)
    clip = subprocess.run(['xclip', '-selection', 'clipboard', '-o'], capture_output=True, text=True)
    print('clipboard bytes', len(clip.stdout), clip.stdout[:120])
finally:
    child.terminate(); child.wait(timeout=10)
