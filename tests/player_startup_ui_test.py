"""Start the native player from external working directories with private data."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from world_map_test_support import private_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    binary = args.binary.resolve()
    output = root / 'work/island-buy-ui-test/player-startup'
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=root, check=True)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.driver_source.resolve() / 'tests'))
    from ui_driver import UiDriver

    for index, cwd in enumerate((root, root.parents[2])):
        with tempfile.TemporaryDirectory(dir=output) as directory:
            profile = Path(directory)
            records = profile / 'games/arcade.shovey-player/records'
            records.mkdir(parents=True)
            (records / 'level-updates').write_text('off')
            driver = UiDriver(profile / 'driver')
            log_path = output / f'cwd-{index}.log'
            with log_path.open('w') as log:
                child = subprocess.Popen([str(binary)], cwd=cwd,
                    env=private_environment(profile, driver.environment()),
                    stdout=log, stderr=subprocess.STDOUT)
                driver.attach(child, log_path)
                try:
                    driver.wait(label='Play', role='button', timeout=60)
                    driver.wait_idle(frames=4)
                    assert child.poll() is None, 'External cwd prevented native startup'
                    # The desktop may already have Shovey open. A concurrent
                    # process must preserve its exclusive durable-storage lock.
                    second_log = output / f'locked-{index}.log'
                    with second_log.open('w') as second_output:
                        second = subprocess.run([str(binary)], cwd=cwd,
                            env=private_environment(profile), stdout=second_output,
                            stderr=subprocess.STDOUT, timeout=20)
                    assert second.returncode == 1, second.returncode
                    with second_log.open() as saved:
                        assert 'could not open collection or game' in saved.read(2048)
                    assert child.poll() is None, 'Concurrent startup disturbed the first player'
                    driver.wait_idle(frames=4)
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)
            # Releasing our test process releases the lock: the same profile
            # and external cwd must then start normally, without deleting data.
            driver.reset()
            with (output / f'reopen-{index}.log').open('w') as log:
                child = subprocess.Popen([str(binary)], cwd=cwd,
                    env=private_environment(profile, driver.environment()),
                    stdout=log, stderr=subprocess.STDOUT)
                driver.attach(child, output / f'reopen-{index}.log')
                try:
                    driver.wait(label='Play', role='button', timeout=60)
                    driver.wait_idle(frames=4)
                    assert child.poll() is None
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)
    print('Native private startup local test passed: external cwd, exclusive profile lock, '
          'first player preserved, same profile reopened after test lock release')


if __name__ == '__main__':
    main()
