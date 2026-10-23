#!/usr/bin/env python3
"""Shovey's touch controls on a real Android phone, without screenshots.

Installs a debuggable Shovey under an isolated package, turns on Kryon's test
driver in its private files, and plays through the real interface by widget
labels: the first level asks how to move, Help chooses the movement pad, the board keeps
clear of it, every arm steps the right way, holding repeats, the hub stops,
the choice survives a restart and switching back removes the pad. The phone
is left as it was: the test package is removed and the app that was in front
comes back.

    python3 tests/android_controls_device_test.py --serial ZE2223BQZT \\
        --apk ../arcade/build/shovey-test-unsigned.apk
"""
import argparse
import json
import re
import subprocess
import sys
import time

ACTIVITY = 'xyz.waozi.arcade.ArcadeActivity'


class Phone:
    def __init__(self, serial, package):
        self.serial, self.package, self.number = serial, package, 0
        self.folder = 'files/kryon-test-driver'
        self.pids = []

    def adb(self, *args, check=True):
        result = subprocess.run(['adb', '-s', self.serial, *args], capture_output=True, text=True, timeout=120)
        if check and result.returncode != 0:
            raise RuntimeError(' '.join(args) + ': ' + result.stderr + result.stdout)
        return result.stdout

    def private(self, script, check=True):
        return self.adb('shell', f"run-as {self.package} sh -c '{script}'", check=check)

    def command(self, verb, timeout=30, **fields):
        self.number += 1
        line = '\\t'.join([str(self.number), verb] + [f'{name}={value}' for name, value in fields.items()])
        folder = self.folder
        self.private(f'printf "{line}\\n" > {folder}/command.next && mv {folder}/command.next {folder}/command')
        end = time.time() + timeout
        while time.time() < end:
            text = self.private(f'cat {folder}/reply 2>/dev/null && rm -f {folder}/reply', check=False)
            if text.strip():
                reply = json.loads(text)
                if reply.get('serial') == self.number:
                    if not reply.get('ok'):
                        raise AssertionError(f'{verb} failed: {reply.get("error")}')
                    return reply
            time.sleep(0.1)
        raise TimeoutError(f'no reply to {verb}')

    def settle(self, frames=6, timeout=40, moving=1.0):
        """Wait until the screen is still. A lit house sparkles and idle
        pieces glow, so a level may never be still: once it has kept drawing
        for a while, steps and screen changes have finished."""
        start = self.command('status')
        end = time.time() + timeout
        while time.time() < end:
            status = self.command('status')
            if status.get('stable_frames', 0) >= frames:
                return
            if time.time() - (end - timeout) >= moving and status.get('frame', 0) - start.get('frame', 0) >= 30:
                return
            time.sleep(0.2)
        raise TimeoutError('the screen did not settle')

    def find(self, **selector):
        return self.command('find', **selector).get('nodes', [])

    def one(self, **selector):
        nodes = self.find(**selector)
        assert nodes, f'no widget matches {selector}'
        return nodes[0]

    def press(self, **selector):
        self.command('press', **selector)
        self.settle()

    def hold(self, x, y, seconds):
        self.command('pointer', x=round(x), y=round(y), down=1)
        time.sleep(seconds)
        self.command('pointer', x=round(x), y=round(y), down=0)
        self.command('pointer', real=1)
        self.settle(4)

    def drag(self, x, y, dx, dy):
        self.command('pointer', x=round(x), y=round(y), down=1)
        for part in range(1, 5):
            self.command('pointer', x=round(x + dx * part / 4), y=round(y + dy * part / 4), down=1)
        self.command('pointer', x=round(x + dx), y=round(y + dy), down=0)
        self.command('pointer', real=1)
        self.settle(4)

    def launch(self):
        self.adb('shell', 'am', 'start', '-W', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER',
                 '-n', f'{self.package}/{ACTIVITY}')
        self.pids.append(self.adb('shell', 'pidof', self.package, check=False).strip())
        self.settle()

    def stop(self):
        self.adb('shell', 'am', 'force-stop', self.package)


def shovey(phone):
    node = phone.one(label='Shovey', role='image')
    return node['x'], node['y'], node['width']


def moved(before, after):
    """Whole cells moved across and down."""
    cell = before[2]
    return round((after[0] - before[0]) / cell), round((after[1] - before[1]) / cell)


def overlaps(a, b):
    return a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height']


def foreground(phone):
    text = phone.adb('shell', 'dumpsys', 'activity', 'activities')
    match = re.search(r'(?:m|top)?ResumedActivity: ActivityRecord\{\S+ \S+ (\S+?)/(\S+) ', text)
    return (match.group(1), match.group(2)) if match else None


def errors(phone):
    """Kryon errors and crashes logged by this run's processes."""
    log = phone.adb('logcat', '-d', check=False)
    found = []
    for line in log.splitlines():
        fields = line.split()
        if len(fields) > 4 and fields[2] in phone.pids and (fields[4] in ('E', 'F') and ('kryon' in line or 'DEBUG' in line)
                                                           or 'FATAL EXCEPTION' in line or 'Fatal signal' in line):
            found.append(line)
    return found


def run(phone, apk):
    phone.adb('install', '-r', '-t', apk)
    phone.adb('shell', 'pm', 'clear', phone.package)
    phone.private(f'mkdir -p {phone.folder}')
    phone.adb('logcat', '-c')
    phone.launch()

    # The first level asks how to move, with both ways shown; choose swipe.
    phone.press(label='Play')
    assert phone.find(label='How do you want to move?'), 'the first level did not ask how to move'
    assert phone.find(label='Swipe and tap') and phone.find(label='Movement pad'), 'a way to move is missing'
    phone.press(label='Swipe and tap')
    assert not phone.find(label='How do you want to move?'), 'the question stayed open'
    assert not phone.find(label='Movement pad'), 'the pad showed after choosing swipe and tap'
    assert phone.find(label='Walk to the house to finish the level.', role='text'), 'the first level shows no tip'
    print('first level: asked how to move, swipe and tap chosen, its tip shows')
    # A swipe on the board steps.
    start = shovey(phone)
    phone.drag(start[0] + start[2] / 2, start[1] + start[2] / 2, -start[2] * 3, 0)
    assert moved(start, shovey(phone))[0] < 0, 'a swipe to the left did not move Shovey'
    print('swipe and tap: default, a swipe steps')

    # Help offers the choice; the movement pad becomes the selected one.
    phone.press(key=20017)
    swipe, pad = phone.one(label='Swipe and tap'), phone.one(label='Movement pad')
    assert swipe['selected'] and not pad['selected'], 'swipe and tap was not the selected default'
    phone.press(label='Movement pad')
    assert phone.one(label='Movement pad')['selected'] and not phone.one(label='Swipe and tap')['selected']
    # Closing the guide returns to the level, which now has the pad.
    phone.press(key=20017)
    assert phone.find(label='Restart'), 'closing help left the level'
    pad = phone.one(label='Movement pad', role='button')
    print('help: movement pad chosen, close returns to the level')

    # The pad sits in the bottom left and nothing on the board lies under it.
    screen = phone.one(role='screen')
    assert pad['x'] < screen['width'] / 3 and pad['y'] + pad['height'] > screen['y'] + screen['height'] * 0.7, pad
    board = [node for node in phone.command('tree')['nodes'] if node.get('kind') == 'image' and node.get('width', 0) < pad['width']
             and node.get('label') not in ('', None)]
    assert board and not any(overlaps(node, pad) for node in board), 'the board lies under the pad'
    print('pad: bottom left, clear of the board')

    third = pad['width'] / 3
    arms = {'left': (pad['x'] + third / 2, pad['y'] + third * 1.5), 'up': (pad['x'] + third * 1.5, pad['y'] + third / 2),
            'right': (pad['x'] + third * 2.5, pad['y'] + third * 1.5), 'down': (pad['x'] + third * 1.5, pad['y'] + third * 2.5)}
    expected = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}
    walked = set()
    for _ in range(2):
        for arm in ('left', 'right', 'down', 'up'):
            before = shovey(phone)
            phone.hold(*arms[arm], 0.2)
            step = moved(before, shovey(phone))
            if step != (0, 0):
                sign = (step[0] > 0) - (step[0] < 0), (step[1] > 0) - (step[1] < 0)
                assert sign == expected[arm], f'{arm} moved Shovey {step}'
                walked.add(arm)
    assert walked == set(arms), f'arms that never moved Shovey: {set(arms) - walked}'
    print('pad: every arm steps its own way')

    # Holding an arm keeps walking; resting on the hub does not.
    before = shovey(phone)
    phone.hold(pad['x'] + pad['width'] / 2, pad['y'] + pad['height'] / 2, 1.0)
    assert moved(before, shovey(phone)) == (0, 0), 'the hub moved Shovey'
    longest = 0
    for arm in ('left', 'right', 'down', 'up'):
        before = shovey(phone)
        phone.hold(*arms[arm], 1.0)
        step = moved(before, shovey(phone))
        longest = max(longest, abs(step[0]) + abs(step[1]))
    assert longest >= 3, f'holding an arm walked at most {longest} cells in a second'
    print(f'pad: holding repeats ({longest} cells in a second), the hub stops')

    # The choice survives a restart.
    phone.stop()
    phone.launch()
    phone.press(label='Play')
    assert phone.find(label='Movement pad', role='button'), 'the movement pad was forgotten after a restart'
    print('restart: the movement pad stays chosen')

    # Back to swipe and tap: the pad goes and swipes step again.
    phone.press(key=20017)
    phone.press(label='Swipe and tap')
    phone.press(key=20017)
    assert not phone.find(label='Movement pad', role='button'), 'the pad stayed after choosing swipe and tap'
    print('swipe and tap: chosen again, the pad is gone')

    problems = errors(phone)
    assert not problems, '\n'.join(problems)
    print('log: no Kryon errors or crashes')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--apk', required=True, help='a debuggable build with an isolated application id')
    parser.add_argument('--package', default='xyz.waozi.shovey.verify')
    parser.add_argument('--keep', action='store_true', help='leave the test package installed')
    args = parser.parse_args()
    if args.package in ('xyz.waozi.shovey', 'xyz.waozi.arcade'):
        sys.exit('use an isolated test package, never the installed app')
    phone = Phone(args.serial, args.package)
    previous = foreground(phone)
    try:
        run(phone, args.apk)
    finally:
        phone.stop()
        if not args.keep:
            phone.adb('uninstall', args.package, check=False)
        if previous and previous[0] != args.package:
            phone.adb('shell', 'am', 'start', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER',
                      '-n', f'{previous[0]}/{previous[1]}', check=False)
    print('Shovey touch controls passed on', args.serial)


if __name__ == '__main__':
    main()
