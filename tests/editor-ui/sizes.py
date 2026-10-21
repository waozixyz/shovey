"""Disposable private-display check of the editor at phone sizes."""
import os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, '/mnt/storage/Projects/waozixyz/inbe/tests')
from ui_driver import UiDriver
out = Path('/mnt/storage/Projects/waozixyz/shovey/build/ui-test')
driver = UiDriver(out / 'driver')
log = (out / 'sizes.log').open('w')
child = subprocess.Popen([str(out / 'player/shovey')], cwd=str(out / 'player'),
    env=os.environ | driver.environment() | {'ARCADE_DATA': str(out / 'profile'), 'LANG': 'de_DE.UTF-8'}, stdout=log, stderr=subprocess.STDOUT)
driver.attach(child, out / 'sizes.log')
def resize(w, h):
    wid = subprocess.run(['xdotool', 'search', '--pid', str(child.pid)], capture_output=True, text=True).stdout.split()
    for w_id in wid:
        subprocess.run(['xdotool', 'windowsize', w_id, str(w), str(h)])
    time.sleep(0.8)
def shot(name):
    time.sleep(0.5)
    subprocess.run(['import', '-window', subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0], str(out / f'{name}.png')], check=False)
try:
    driver.press(label='Shovey Editor', role='button')
    driver.press(label='Island', role='button')
    driver.press(label='Neues Level')
    driver.wait(label='Spielfeld: Tippen oder Ziehen zum Malen')
    resize(800, 400); shot('landscape-edit')
    resize(360, 640); shot('portrait-edit')
    driver.press(label='Spielen')
    shot('portrait-play')
    resize(800, 400); shot('landscape-play')
finally:
    child.terminate(); child.wait(timeout=10)
