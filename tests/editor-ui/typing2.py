import os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, '/mnt/storage/Projects/waozixyz/inbe/tests')
from ui_driver import UiDriver
out = Path('/mnt/storage/Projects/waozixyz/shovey/build/ui-test')
records = out / 'profile/games/arcade.shovey-editor/records'
driver = UiDriver(out / 'driver')
log = (out / 'typing2.log').open('w')
child = subprocess.Popen([str(out / 'player/shovey')], cwd=str(out / 'player'),
    env=os.environ | driver.environment() | {'ARCADE_DATA': str(out / 'profile'), 'LANG': 'en_US.UTF-8'}, stdout=log, stderr=subprocess.STDOUT)
driver.attach(child, out / 'typing2.log')
try:
    driver.press(label='Shovey Editor', role='button')
    driver.press(label='Classic', role='button')
    driver.press(label='Level 1')
    driver.press(role='text_field', index=0)
    time.sleep(0.5)
    wid = subprocess.run(['xdotool', 'search', '--pid', str(child.pid)], capture_output=True, text=True).stdout.split()[-1]
    subprocess.run(['xdotool', 'type', '--window', wid, '--delay', '60', 'Lagoon Een'])
    time.sleep(0.5)
    driver.key('enter')
    time.sleep(0.5)
    print([l for l in (records / 'classic-levels').read_text().splitlines() if l.startswith('level 1 ')])
    driver.press(label='Levels')
    driver.wait(label='Lagoon Een')
    driver.press(label='Back')
    driver.press(label='Explore')
    driver.press(role='text_field', index=0)
    subprocess.run(['xdotool', 'type', '--window', wid, '--delay', '60', 'ada_1'])
    time.sleep(0.5)
    print([n['label'] for n in driver.find(role='text_field')])
    subprocess.run(['import', '-window', subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0], str(out / 'explore-typed.png')])
finally:
    child.terminate(); child.wait(timeout=10)
