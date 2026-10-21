import os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, '/mnt/storage/Projects/waozixyz/inbe/tests')
from ui_driver import UiDriver
out = Path('/mnt/storage/Projects/waozixyz/shovey/build/ui-test')
driver = UiDriver(out / 'driver')
log = (out / 'copy.log').open('w')
child = subprocess.Popen([str(out / 'player/shovey')], cwd=str(out / 'player'),
    env=os.environ | driver.environment() | {'ARCADE_DATA': str(out / 'profile'), 'LANG': 'en_US.UTF-8'}, stdout=log, stderr=subprocess.STDOUT)
driver.attach(child, out / 'copy.log')
try:
    driver.press(label='Shovey Editor', role='button')
    driver.press(label='Export')
    driver.wait(contains='proven levels as text')
    driver.press(label='Copy')
    time.sleep(0.8)
    clip = subprocess.run(['xclip', '-selection', 'clipboard', '-o'], capture_output=True, text=True, timeout=5)
    print('clipboard bytes', len(clip.stdout)); print(clip.stdout[:400])
    subprocess.run(['import', '-window', subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0], str(out / 'export.png')])
finally:
    child.terminate(); child.wait(timeout=10)
