"""Final packaged Classic opens offline; real host curl transport is observed."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time
from world_map_test_support import private_environment, digest, assert_fullscreen_map, start_map_destination, enter_classic_map

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--driver-source', type=Path, required=True)
parser.add_argument('--tripwire', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.driver_source / 'tests'))
from ui_driver import UiDriver
output = ROOT / 'work/map-offline-proof'
subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT, check=True)
output.mkdir(parents=True, exist_ok=True)
counts = {}
processes = {}
for phase, setting in (('offline', 'off'), ('positive', 'on')):
    profile = output / phase
    if profile.exists():
        assert profile.parent == output and profile.name in ('offline', 'positive')
        shutil.rmtree(profile)
    records = profile / 'games/arcade.shovey-player/records'
    records.mkdir(parents=True, exist_ok=True)
    (records / 'level-updates').write_text(setting)
    (records / 'controls').write_text('off')
    triplog = output / f'{phase}-transport.log'
    triplog.unlink(missing_ok=True)
    driver = UiDriver(profile / 'driver')
    environment = private_environment(profile, driver.environment() | {
        'LD_PRELOAD': str(args.tripwire.resolve()), 'SHOVEY_HTTP_TRIPWIRE': str(triplog)})
    with (output / f'{phase}.log').open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
            env=environment, stdout=log, stderr=subprocess.STDOUT)
        driver.attach(child, output / f'{phase}.log')
        try:
            driver.wait(label='Play', role='button', timeout=60)
            window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0]
            assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
            driver.press(label='Play', role='button')
            enter_classic_map(driver)
            start_map_destination(driver, 1)
            driver.wait(contains='Level 1 / ', role='text', timeout=45)
            if driver.find(label='Got it', role='button'):
                driver.press(label='Got it')
            driver.wait(label='Levels', role='button')
            assert not driver.find(contains='Request rejected'), 'Actual package quota rejected bundled Classic'
            if phase == 'offline':
                driver.press(label='Levels', role='button')
                driver.wait(key=33001, role='button')
                driver.wait_idle(frames=8)
                subprocess.run(['import', '-window', window, str(output / 'offline-map.png')], check=True)
                driver.press(key=20022)
                driver.wait(contains='Level 1 / ', role='text')
                driver.wait_idle(frames=8)
            else:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if triplog.exists() and 'attempt' in triplog.read_text():
                        break
                    driver.wait_idle(frames=3, timeout=1)
            assert (records / 'level-updates').read_text() == setting
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
    entries = [line.split() for line in triplog.read_text().splitlines()]
    assert sum(event == ['loaded', str(child.pid)] for event in entries) == 1, 'Tripwire not loaded into actual native host'
    attempts = [int(pid) for kind, pid in entries if kind == 'attempt']
    assert all(pid == child.pid for pid in attempts), 'Subprocess transport attempts cannot prove actual host interception'
    processes[phase] = child.pid
    counts[phase] = len(attempts)
    assert counts[phase] == 0 if phase == 'offline' else counts[phase] > 0, counts
staging = args.binary.resolve().parents[1]
classic = staging / 'games/shovey.zx'
collection = args.binary.resolve().parent / 'shovey.zx'
result = {'actual_host_pids': processes, 'http_attempts': counts['offline'], 'positive_control_real_host_http_attempts': counts['positive'],
    'method': 'LD_PRELOAD curl_easy_perform tripwire loaded in each actual native host; positive downloads-on path invokes real host transport; no outbound transfer performed',
    'downloads_off': True, 'classic_opened': True, 'quota_rejected': False,
    'binary_sha256': digest(args.binary), 'view_source_sha256': digest(ROOT / 'src/world_map_view.zi'),
    'tripwire_sha256': digest(args.tripwire), 'classic': {'bytes': classic.stat().st_size, 'sha256': digest(classic)},
    'collection': {'bytes': collection.stat().st_size, 'sha256': digest(collection)},
    'native_runtime_export_tree_bytes': sum(p.stat().st_size for p in args.binary.parent.rglob('*') if p.is_file() and 'c' not in p.relative_to(args.binary.parent).parts)}
(output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print('Final packaged Classic local offline UI test passed: downloadsOFF, real transport attempts0; positive actual host transport observed', counts['positive'])
