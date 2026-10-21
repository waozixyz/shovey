"""Disposable private-display check of the Shovey Editor."""
import os, subprocess, sys, time, json
from pathlib import Path
sys.path.insert(0, '/mnt/storage/Projects/waozixyz/inbe/tests')
from ui_driver import UiDriver
out = Path('/mnt/storage/Projects/waozixyz/shovey/build/ui-test')
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
profile = out / 'profile'
driver = UiDriver(out / 'driver')
log = (out / 'smoke.log').open('w')
child = subprocess.Popen([str(out / 'player/shovey')], cwd=str(out / 'player'),
    env=os.environ | driver.environment() | {'ARCADE_DATA': str(profile), 'LANG': 'en_US.UTF-8'}, stdout=log, stderr=subprocess.STDOUT)
driver.attach(child, out / 'smoke.log')
def shot(name):
    subprocess.run(['import', '-window', subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0], str(out / f'{name}.png')], check=False)
try:
    driver.wait(label='Shovey Editor', role='button')
    driver.press(label='Shovey Editor', role='button')
    driver.wait(label='Shovey Editor', role='text')
    time.sleep(0.5); shot('home')
    print(driver.text())
finally:
    child.terminate(); child.wait(timeout=10)
