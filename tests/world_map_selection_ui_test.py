"""Exercise map selection separately from Play using a private host and saves."""
import argparse
import contextlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from shovey_standalone_ui_test import answer_cover_question, answer_level_updates
from world_map_test_support import assert_fullscreen_map, private_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'work/world-map-selection-test'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver
    driver = UiDriver(output / 'driver')

    @contextlib.contextmanager
    def app(profile):
        with (output / 'host.log').open('w') as log:
            child = subprocess.Popen([str(args.binary.resolve())], cwd=args.binary.resolve().parent,
                env=private_environment(profile, driver.environment()), stdout=log, stderr=subprocess.STDOUT)
            driver.attach(child, output / 'host.log')
            try:
                answer_cover_question(driver)
                driver.press(label='Play', role='button')
                assert_fullscreen_map(driver)
                assert not any(n.get("key") in (20510,20511) for n in driver.tree()), "Duplicate title menu after Play"
                yield child
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)

    with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as tmp:
        profile = Path(tmp)
        with app(profile) as child:
            windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)], text=True).split()
            assert len(windows) == 1
            window = windows[0]
            assert subprocess.check_output(['xdotool', 'getwindowpid', window], text=True).strip() == str(child.pid)
            subprocess.run(['xdotool', 'windowsize', '--sync', window, '320', '720'], check=True)
            driver.wait_idle(frames=4)
            for w,h in ((320,720),(600,1000),(960,600)):
                subprocess.run(['xdotool','windowsize','--sync',window,str(w),str(h)],check=True)
                driver.wait_idle(frames=8)
                # The 37 v5 continuous sections; each fills the window's cross axis.
                painted = [n for n in driver.tree() if 60001 <= n.get('key',0) <= 60037 and n.get('visible')]
                assert painted, 'Map art missing'
                assert all(n['detail'].split('/assets/shovey/')[-1].startswith('world-map/continuous-') for n in painted), painted
                subprocess.run(['import','-window',window,str(output / f'fit-{w}-{h}.png')],check=True)
                for tile in painted:
                    if w < h:
                        # Portrait fits the width, but never below 0.41 px per art
                        # px; a wider painting pans sideways within the window.
                        expected = max(w, 1086 * .41)
                        assert abs(tile['width']-expected) <= 1 and w - expected - 1 <= tile['x'] <= 1, tile
                    else:
                        # Landscape may lift the art by at most the 112px bottom
                        # panel so the framed level stays above it.
                        assert -113 <= tile['y'] <= 1 and abs(tile['height']-h) <= 1, tile
            subprocess.run(['xdotool','windowsize','--sync',window,'320','720'],check=True)
            driver.wait_idle(frames=8)
            assert_fullscreen_map(driver)
            assert driver.wait(key=33001, role='button')['selected']
            assert driver.wait(key=20122, role='button')['enabled']
            subprocess.run(['import', '-window', window, str(output / 'garden-320.png')], check=True)
            assert_fullscreen_map(driver)
            node = driver.wait(key=33001, role='button')
            assert node['y'] + node['height'] <= 608, ('Node hidden beneath bottom panel',node)
            subprocess.run(['xdotool', 'mousemove', '--window', window, str(int(node['x'] + node['width']/2)), str(int(node['y'] + node['height']/2)), 'click', '--repeat', '2', '--delay', '120', '1'], check=True)
            answer_level_updates(driver)
            driver.wait(contains='Level 1 / ', role='text', timeout=30)
        record = profile / 'games/arcade.shovey/records/local.campaign'
        text = record.read_text()
        header, marks = (6, 1000) if text.startswith(('C5', 'C6')) else (4, 175)
        record.write_text(text[:2] + f'{99:0{header - 2}x}' + '1' * 98 + '0' * (marks - 98) + text[header + marks:])
        with app(profile):
            assert driver.wait(key=33001, role='button')['selected']
            driver.key('up')
            assert driver.wait(key=33002, role='button')['selected']
            driver.wait(label='Level 2', role='text')
            driver.press(key=33001, role='button')
            assert driver.wait(key=33001, role='button')['selected']
            assert_fullscreen_map(driver)
            # The level select has no on-screen arrow buttons; W moves like Up.
            assert not any(20123 <= n.get('key', 0) <= 20126 for n in driver.tree()), 'on-screen arrows shown'
            driver.key(87)
            assert driver.wait(key=33002, role='button')['selected']
            driver.press(key=20122, role='button')
            driver.wait(contains='Level 2 / ', role='text', timeout=30)
    print('Private map selection local UI test passed: click selects, arrow and WASD keys navigate, no on-screen arrows, Play opens selected board, level 1 retained')


if __name__ == '__main__':
    main()
