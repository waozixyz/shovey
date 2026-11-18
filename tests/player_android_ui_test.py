"""Exercise a separate debug install on a USB Android phone through Kryon's driver."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
import zipfile

from world_map_test_support import assert_fullscreen_map, enter_classic_map, start_map_destination, wait_gameplay

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'xyz.waozi.shovey.test'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--driver-source', type=Path, required=True)
    parser.add_argument('--profile-only', action='store_true',
                        help='check native startup, Profile and Android Back without opening Classic')
    args = parser.parse_args()
    sys.path.insert(0, str(args.driver_source.resolve()))
    from ui_driver import UiDriver, escape

    def adb(*command, **options):
        return subprocess.run(['adb', '-s', args.serial, *command], check=True,
                              capture_output=True, text=True, timeout=30, **options).stdout

    def remote(script, **options):
        command = f'run-as {PACKAGE} sh -c {shlex.quote(script)}'
        return adb('exec-out', command, **options)

    class AndroidDriver(UiDriver):
        pid = ''

        def _failure(self, message):
            if self.pid:
                log = adb('logcat', '-d', '-t', '120', '--pid=' + self.pid)
                (self.directory.parent / 'moto-native.log').write_text(log)
            return super()._failure(message)

        def reset(self):
            remote('mkdir -p files/kryon-test-driver; '
                   'rm -f files/kryon-test-driver/command files/kryon-test-driver/command.tmp '
                   'files/kryon-test-driver/reply files/kryon-test-driver/reply.tmp')

        def send(self, verb, timeout=30, **fields):
            self.serial += 1
            parts = [str(self.serial), verb]
            for name, value in fields.items():
                if value is not None:
                    value = ('1' if value else '0') if isinstance(value, bool) else value
                    parts.append(f'{name}={escape(value)}')
            command = shlex.quote('\t'.join(parts) + '\n')
            remote('cd files/kryon-test-driver && rm -f reply && '
                   f"printf %s {command} > command.tmp && mv command.tmp command")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                text = remote('cd files/kryon-test-driver && if test -f reply; then cat reply; fi')
                if text:
                    reply = json.loads(text)
                    if reply.get('serial') == self.serial:
                        if verb == 'tree':
                            self.last = reply
                        return reply
                time.sleep(.1)
            raise self._failure(f'{verb}: no Android reply within {timeout} s')

    assert adb('get-state').strip() == 'device'
    assert int(adb('shell', 'getprop', 'ro.build.version.sdk').strip()) >= 27, 'wrap.sh needs Android 8.1+'
    with zipfile.ZipFile(args.apk) as archive:
        names = archive.namelist()
        assert any(name.startswith('lib/') and name.endswith('/wrap.sh') for name in names), 'build with KRYON_TEST_DRIVER=1'
    # Check the APK's identity before installing: never overwrite the owner's app.
    sdk = Path.home() / 'Android/Sdk'
    aapt = sdk / 'build-tools/36.0.0/aapt'
    badging = subprocess.check_output([aapt, 'dump', 'badging', args.apk], text=True)
    assert f"package: name='{PACKAGE}'" in badging, 'use --application-id xyz.waozi.shovey.test'
    assert 'application-debuggable' in badging, 'run-as and wrap.sh need a debug APK'
    adb('install', '-r', str(args.apk.resolve()))
    print('Installed separate Android test package', flush=True)
    adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
    adb('shell', 'wm', 'dismiss-keyguard')
    adb('shell', 'am', 'force-stop', PACKAGE)
    # These records belong solely to this disposable test application.
    remote('mkdir -p files/games/arcade.shovey-player/records; '
           'printf off > files/games/arcade.shovey-player/records/level-updates; '
           'printf off > files/games/arcade.shovey-player/records/controls')
    driver = AndroidDriver(ROOT / 'build/player/android/driver')
    campaign = 'files/games/arcade.shovey/records/local.campaign'

    def saved_game():
        return remote(f'if test -f {campaign}; then cat {campaign}; fi')

    def launch():
        adb('shell', 'am', 'start', '-W', '-n', PACKAGE + '/xyz.waozi.shovey.ShoveyActivity')
        driver.pid = adb('shell', 'pidof', PACKAGE).strip().split()[0]
        driver.send('status', timeout=120)
        driver.wait(label='Play', role='button', timeout=60)
        driver.wait_idle(frames=4)
        if driver.find(label='Download new levels when they come out?', role='text'):
            driver.press(label='Not now', role='button')
            driver.wait_gone(label='Download new levels when they come out?', role='text')

    def level():
        driver.press(label='Play', role='button')
        enter_classic_map(driver)
        start_map_destination(driver, 1)
        if driver.find(label='How do you want to move?', role='text'):
            driver.press(label='Swipe and tap', role='button')
            driver.wait_gone(label='How do you want to move?', role='text')
        if driver.find(label='Got it', role='button'):
            driver.press(label='Got it', role='button')
        wait_gameplay(driver, timeout=60)

    try:
        adb('shell', 'am', 'force-stop', PACKAGE)
        launch()
        print('Native title and test driver ready', flush=True)
        driver.press(key=49204, role='button')
        driver.wait(label='Sign in', timeout=60)
        driver.key(4)
        driver.wait(label='Play', role='button')
        print('Profile and Android Back passed', flush=True)
        if args.profile_only:
            print('PASS Android USB host: native startup, Profile and Android Back; gameplay not exercised')
            return
        level()
        print('Classic map and gameplay ready', flush=True)
        assert driver.find(label='Shovey', role='image', visible=True), 'the board has no player'
        driver.press(label='Restart', role='button')
        wait_gameplay(driver)
        fresh = saved_game()
        moved = fresh
        for key in ('left', 'up', 'right', 'down'):
            driver.key(key)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                moved = saved_game()
                if moved != fresh:
                    break
                time.sleep(.1)
            if moved != fresh:
                break
        assert moved and moved != fresh, 'movement did not save the campaign'
        driver.key(4)  # Android Back, through the host's key input path.
        assert_fullscreen_map(driver)
        driver.key(4)
        driver.wait(label='Play', role='button')
        adb('shell', 'am', 'force-stop', PACKAGE)
        driver.reset()
        launch()
        level()
        assert saved_game() == moved, 'saved move was lost across app restart'
        print('PASS Android USB: native startup, Classic map/gameplay, movement, Restart, Back, Profile and app restart')
    finally:
        adb('shell', 'am', 'force-stop', PACKAGE)


if __name__ == '__main__':
    main()
