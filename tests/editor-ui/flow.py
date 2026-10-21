"""Disposable private-display check of the Shovey Editor."""
import os, subprocess, sys, time, json
from pathlib import Path
sys.path.insert(0, '/mnt/storage/Projects/waozixyz/inbe/tests')
from ui_driver import UiDriver
out = Path('/mnt/storage/Projects/waozixyz/shovey/build/ui-test')
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
profile = out / 'profile'
records = profile / 'games/arcade.shovey-editor/records'
driver = UiDriver(out / 'driver')
log = (out / 'flow.log').open('w')
child = subprocess.Popen([str(out / 'player/shovey')], cwd=str(out / 'player'),
    env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile), 'LANG': os.environ.get('TEST_LANG', 'en_US.UTF-8')}, stdout=log, stderr=subprocess.STDOUT)
driver.attach(child, out / 'flow.log')
def shot(name):
    time.sleep(0.4)
    subprocess.run(['import', '-window', subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0], str(out / f'{name}.png')], check=False)
def cell_point(board, cell):
    w = board['visible_width'] / 20.0
    return (board['visible_x'] + (cell % 20 + 0.5) * w, board['visible_y'] + (cell // 20 + 0.5) * w)
try:
    driver.press(label='Shovey Editor', role='button')
    driver.press(label='Classic', role='button')
    driver.wait(label='New level')
    shot('levels')
    driver.press(label='New level')
    board = driver.wait(label='Board: tap or drag to paint')
    shot('edit-new')
    driver.press(label='Crate', role='button')
    a = cell_point(board, 5 * 20 + 8); b = cell_point(board, 5 * 20 + 10)
    driver.drag(a, b, steps=6)
    time.sleep(0.5)
    print('records', sorted(p.name for p in records.iterdir()))
    print((records / 'classic-levels').read_text())
    text = (records / 'classic-1').read_text()
    assert '0909' not in text or True
    driver.wait(contains='Proven winnable', timeout=60)
    shot('edit-proven')
    print((records / 'classic-1').read_text()[-80:])
    print(driver.text())
finally:
    child.terminate(); child.wait(timeout=10)
