"""Solve a real board in an isolated profile and inspect the results screen."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from PIL import Image

from shovey_standalone_ui_test import answer_cover_question, answer_level_updates
from world_map_test_support import private_environment, start_map_destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'work/move-stars-score/ui'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    output.mkdir(parents=True, exist_ok=True)
    # Every shipped locale has a translated title with exactly one label slot.
    for locale in (root / 'src/locales').glob('*.txt'):
        entries = dict(re.findall(r'\[([^\]]+)\]\n(.*?)\n---', locale.read_text(), re.S))
        assert entries['shovey_result_complete'].count('%') == 1, locale
        assert entries['shovey_result_score'] and entries['shovey_result_moves'], locale
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')
    # Read only the authored route; gameplay uses the actual app's input path.
    release = solutions = False
    route = ''
    with (root / 'src/levels.zi').open() as source:
        for line in source:
            if '#if #defined(SHOVEY_RELEASE)' in line:
                release = True
            if release and line.startswith('ShoveyLevelSolution ::'):
                solutions = True
            match = re.search(r'if number == 1 \{ return "([^"]+)"', line)
            if solutions and match:
                route = match[1]
                break
    assert route
    assert set(route) <= set('0123'), route
    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as tmp:
        profile = Path(tmp)
        with (output / 'host.log').open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, output / 'host.log')
            try:
                answer_cover_question(driver)
                windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
                assert len(windows) == 1
                window = windows[0]
                assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
                subprocess.run(['xdotool', 'windowsize', '--sync', window, '400', '800'], check=True)
                driver.press(label='Play', role='button')
                start_map_destination(driver, 1)
                answer_level_updates(driver)
                driver.wait(contains='Level 1 / ', role='text')
                if driver.find(label='How do you want to move?', role='text'):
                    driver.press(label='Swipe and tap')
                    driver.wait_gone(label='How do you want to move?', role='text')
                if driver.find(label='Got it', role='button'):
                    driver.press(label='Got it', role='button')
                time.sleep(1)
                campaign = profile / "games/arcade.shovey/records/local.campaign"
                for step, direction in enumerate(route, 1):
                    # Accommodate the board's existing slide animation.
                    driver.key(('left', 'up', 'right', 'down')[int(direction)])
                    deadline = time.monotonic() + 3
                    while True:
                        text = campaign.read_text()
                        start = 1006 if text.startswith(('C5', 'C6')) else 179
                        recorded = int(text[start + 12:start + 20], 16)
                        if recorded >= step:
                            assert recorded == step, (step, direction, recorded)
                            break
                        if time.monotonic() >= deadline:
                            raise AssertionError(('input did not move', step, direction, recorded, text[start:start + 32]))
                        time.sleep(.05)
                    time.sleep(.15)
                driver.wait(label='Level 1 complete', role='text', timeout=20)
                driver.wait(label='★ ★ ★', role='text')
                driver.wait(label='Score: 1000 / 1000', role='text')
                driver.wait(label=f'Moves: {len(route)}', role='text')
                driver.wait(key=20905, label='Continue', role='button')
                # The result stays readable until the player explicitly continues.
                time.sleep(2)
                driver.wait(label='Level 1 complete', role='text')
                subprocess.run(['import', '-window', window, str(output / 'completion.png')], check=True)
                results = list((profile / 'games/arcade.shovey/records').glob('local.result.*.1'))
                assert len(results) == 1, results
                saved = json.loads(results[0].read_text())
                assert saved['level'] == 1 and saved['moves'] == len(route) and saved['owner'] == ''
                # Levels remains available independently of advancement/payout.
                driver.wait(key=20907, role='button', enabled=True)
                driver.press(key=20907, role='button')
                driver.wait(key=20105, visible=True)
                driver.press(key=20022, role='button')
                driver.wait(label='Level 1 complete', role='text')
                driver.press(key=20905, role='button')
                driver.wait_gone(label='Level 1 complete', role='text')
                driver.wait(contains='Level 2 / ', role='text')
                driver.press(label='Levels', role='button')
                driver.wait(key=33001, role='button')
                driver.press(key=33001, role='button')
                driver.wait(label='Level 1', role='text')
                driver.wait(key=20910, contains='★★★', role='text')
                subprocess.run(['import', '-window', window, str(output / 'completed-map.png')], check=True)
                completed = driver.wait(key=33001, role='button')
                assert completed['detail'] == 'Completed', completed
                # Three bright stars are below the focused circle, clear of the avatar.
                with Image.open(output / 'completed-map.png') as image:
                    cx, cy = driver.center(completed)
                    band = image.convert('RGB').crop((int(cx-26), int(cy+26), int(cx+28), int(cy+46)))
                    assert sum(r > 220 and g > 180 and b < 120 for r,g,b in band.getdata()) > 80, 'Map rating hidden'

            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)
        with (output / 'reload.log').open('w') as log:
            driver.reset()
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, output / 'reload.log')
            try:
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                driver.wait(key=20105)
                driver.press(key=33001, role='button')
                driver.wait(key=20910, contains='★★★', role='text')
                window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()[0]
                for width, height in ((320,720), (960,600)):
                    subprocess.run(['xdotool','windowsize','--sync',window,str(width),str(height)],check=True)
                    driver.wait_idle(frames=6)
                    assert driver.wait(key=33001, role='button')['detail'] == 'Completed'
                    driver.wait(key=20910, contains='★★★', role='text')
                    subprocess.run(['import','-window',window,str(output / f'reloaded-stars-{width}.png')],check=True)
            finally:
                if child.poll() is None: child.terminate()
                child.wait(timeout=10)
        # Legacy campaign completions have no local.result entry. They still
        # get a completion badge, without a fabricated performance rating.
        results[0].unlink()
        with (output / 'legacy.log').open('w') as log:
            driver.reset()
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, output / 'legacy.log')
            try:
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                driver.wait(key=20105)
                driver.press(key=33001, role='button')
                window = subprocess.check_output(['xdotool','search','--onlyvisible','--pid',str(child.pid)],text=True).split()[0]
                subprocess.run(['xdotool','windowmove',window,'0','0'],check=True)
                for width,height in ((320,720),(960,600)):
                    subprocess.run(['xdotool','windowsize','--sync',window,str(width),str(height)],check=True)
                    driver.wait_idle(frames=6)
                    completed = driver.wait(key=33001,role='button')
                    assert completed['detail'] == 'Completed'
                    assert not driver.find(key=20910), 'Legacy completion fabricated a performance rating'
                    screenshot = output / f'legacy-completion-{width}.png'
                    subprocess.run(['import','-window',window,str(screenshot)],check=True)
                    with Image.open(screenshot) as image:
                        cx,cy = driver.center(completed)
                        band = image.convert('RGB').crop((int(cx-14),int(cy+24),int(cx+14),int(cy+48)))
                        assert sum(r > 220 and g > 180 and b < 120 for r,g,b in band.getdata()) > 20, 'Legacy completion star hidden'
                    assert not results[0].exists(), 'Viewing legacy progress wrote a result record'
            finally:
                if child.poll() is None: child.terminate()
                child.wait(timeout=10)
    print('Results local UI test passed: real win, branch-label hook, 3 stars, score1000, durable result, explicit Continue; all12 locale templates present')


if __name__ == '__main__':
    main()
