#!/usr/bin/env python3
"""Check the installed standalone player on an explicitly selected Android phone.

Launches Shovey without resetting its data. Checks its process, startup log and
visible first screen; saves phone-only evidence. Gameplay still needs a UI test.
"""
import argparse
from pathlib import Path
import subprocess
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'xyz.waozi.shovey'
COMPONENT = PACKAGE + '/xyz.waozi.arcade.ArcadeActivity'
FAILURES = ('child verification failed', "application's frame failed",
            'android frame rendering failed', 'FATAL EXCEPTION',
            'Shovey: could not open')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/player/android-smoke')
    args = parser.parse_args()
    output = args.output.resolve()
    subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    adb = ['adb', '-s', args.serial]

    def text(*command, required=True):
        result = subprocess.run([*adb, *command], capture_output=True, text=True, timeout=20)
        if required:
            result.check_returncode()
        return result.stdout.strip()

    assert text('get-state') == 'device', 'Selected phone is not ready'
    text('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
    text('shell', 'wm', 'dismiss-keyguard')
    text('shell', 'am', 'start', '-a', 'android.intent.action.MAIN',
         '-c', 'android.intent.category.LAUNCHER', '-n', COMPONENT)
    deadline = time.monotonic() + 60
    good_since = None
    while time.monotonic() < deadline:
        time.sleep(1)
        pid = text('shell', 'pidof', PACKAGE, required=False)
        assert pid.isdigit(), 'Shovey process is not running'
        log = text('logcat', '-d', '--pid=' + pid, '-v', 'brief', '-t', '300')
        (output / 'startup.log').write_text(log + '\n')
        errors = [line for line in log.splitlines() if any(reason in line for reason in FAILURES)]
        assert not errors, '\n'.join(errors)
        resumed = text('shell', "dumpsys activity activities | grep -m1 -E 'topResumedActivity|mResumedActivity'",
                       required=False)
        if PACKAGE not in resumed:
            good_since = None
            continue
        screenshot = output / 'first-screen.png'
        with screenshot.open('wb') as target:
            subprocess.run([*adb, 'exec-out', 'screencap', '-p'], stdout=target,
                           stderr=subprocess.PIPE, timeout=20, check=True)
        with Image.open(screenshot) as image:
            # Exclude the system navigation bar, then sample the app's content.
            sample = image.convert('RGB').crop((0, 0, image.width, image.height - 60))
            sample.thumbnail((256, 512))
            pixels = list(sample.getdata())
        visible = sum(max(pixel) > 24 for pixel in pixels) / len(pixels)
        colors = len(set(pixels))
        if visible > .05 and colors > 512:
            good_since = good_since or time.monotonic()
            if time.monotonic() - good_since >= 5:
                print(f'Shovey Android local smoke test passed: PID {pid}, visible screen, no startup failure')
                return
        else:
            good_since = None
    raise AssertionError('Shovey did not draw a nonblank first screen within 60 seconds')


if __name__ == '__main__':
    main()
