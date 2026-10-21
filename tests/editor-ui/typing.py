import os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, '/mnt/storage/Projects/waozixyz/inbe/tests')
from ui_driver import UiDriver
out = Path('/mnt/storage/Projects/waozixyz/shovey/build/ui-test')
records = out / 'profile/games/arcade.shovey-editor/records'
driver = UiDriver(out / 'driver')
log = (out / 'typing.log').open('w')
child = subprocess.Popen([str(out / 'player/shovey')], cwd=str(out / 'player'),
    env=os.environ | driver.environment() | {'ARCADE_DATA': str(out / 'profile'), 'LANG': 'en_US.UTF-8'}, stdout=log, stderr=subprocess.STDOUT)
driver.attach(child, out / 'typing.log')
try:
    driver.press(label='Shovey Editor', role='button')
    driver.press(label='Island', role='button')
    driver.press(label='Level 1')
    driver.press(label='Delete')
    driver.wait(contains='Delete now to remove')
    driver.press(label='Delete now')
    driver.wait(label='New level')
    print((records / 'island-levels').read_text())
    print('record left:', (records / 'island-1').read_text() if (records / 'island-1').exists() else None)
finally:
    child.terminate(); child.wait(timeout=10)
