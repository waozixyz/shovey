"""Keep native input usable after a decoder stalls, then retry and reload."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from world_map_test_support import private_environment, start_map_destination

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--driver-source', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
out = root / 'work/loading-recovery-ui-test'
subprocess.run(['git', 'check-ignore', '-q', str(out)], cwd=root, check=True)
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(a.driver_source.resolve()))
from ui_driver import UiDriver

# Inject only the readiness argument at the exact native entry, on x86_64.
# Missing files are also covered by the production loading-policy test.
# GDB owns only this private app, and the build remains untouched.
commands = out / 'stalled.gdb'
commands.write_text('set pagination off\nset confirm off\nset breakpoint pending on\nbreak *player_loading_CollectionNeedsCover\ncommands\nsilent\nset $rcx = 0\ncontinue\nend\nrun\n')
with tempfile.TemporaryDirectory(prefix='profile-', dir=out) as folder:
    profile = Path(folder)
    records = profile / 'games/arcade.shovey-player/records'
    records.mkdir(parents=True)
    (records / 'level-updates').write_text('off')
    driver = UiDriver(profile / 'driver')
    for stalled in (True, False):
        driver.reset()
        log_path = out / ('stalled.log' if stalled else 'reloaded.log')
        command = [str(a.binary.resolve())]
        if stalled:
            command = ['gdb', '--batch', '-x', str(commands), '--args'] + command
        with log_path.open('w') as log:
            child = subprocess.Popen(command, cwd=a.binary.resolve().parent,
                env=private_environment(profile, driver.environment()),
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            driver.attach(child, log_path)
            try:
                driver.wait(label='Play', role='button', timeout=60)
                if stalled:
                    driver.wait(key=49401, role='button')
                    start = time.monotonic()
                driver.wait_gone(key=49401, role='button', timeout=20)
                if stalled:
                    assert time.monotonic() - start >= 7, 'Fault injection did not hold the cover'
                driver.press(label='Play', role='button')
                driver.wait(key=20122, role='button', timeout=20)
                start_map_destination(driver, 1)
                if driver.find(label='How do you want to move?', role='text'):
                    driver.press(label='Swipe and tap', role='button')
                driver.wait(key=20017, role='button')
                if driver.find(label='Got it', role='button'):
                    driver.press(label='Got it', role='button')
                driver.press(key=20017, role='button')
                if stalled:
                    driver.press(key=20903, role='button')
                driver.wait(label='Free hints: 2 · Extra hints: 0', role='text')
                driver.press(key=20905, role='button')
                driver.press(key=20016, role='button')
                driver.press(key=20017, role='button')
                driver.wait(label='Free hints: 2 · Extra hints: 0', role='text')
                driver.press(key=20905, role='button')
                assert child.poll() is None
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=10)
print('Local native loading test passed: forced pending decoder escaped after 8s; input, retry and saved hint allowance survived process reload.')
