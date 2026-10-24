"""A route found once keeps the board winnable after a play goes nowhere."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
EDITOR = Path(os.environ.get('SHOVEY_EDITOR', ROOT / 'build/private-editor/shovey-level-editor'))
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/editor-any-route-test'
output.mkdir(parents=True, exist_ok=True)


def wait(predicate, message, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(.05)
    raise AssertionError(message)


class Driver:
    def __init__(self, folder):
        self.folder, self.number = folder, 0

    def command(self, verb, **fields):
        self.number += 1
        line = '\t'.join([str(self.number), verb] + [f'{name}={value}' for name, value in fields.items()])
        (self.folder / 'command.next').write_text(line + '\n')
        (self.folder / 'command.next').replace(self.folder / 'command')
        reply_path = self.folder / 'reply'
        def answered():
            if not reply_path.exists():
                return None
            reply = json.loads(reply_path.read_text())
            reply_path.unlink()
            return reply if reply.get('serial') == self.number else None
        reply = wait(answered, f'no reply to {verb}')
        assert reply.get('ok'), reply
        return reply

    def labels(self):
        return [node.get('label', '') for node in self.command('tree').get('nodes', [])]

    def showing(self, text):
        return any(text.lower() in label.lower() for label in self.labels())


with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
    profile = Path(temporary)
    drafts = profile / 'backup/editor-drafts'
    for path in (drafts, profile / 'backup/redesign', profile / 'levels', profile / 'scripts', profile / 'build/solver'):
        path.mkdir(parents=True, exist_ok=True)
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
    (profile / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
    (drafts / 'orientation').write_text('portrait')
    # A corridor with the ball, its pit and home, and an open row below it
    # where Shovey can wander off the route.
    cells, tiles = [12] * 240, [12] * 240
    for at in list(range(13, 18)) + list(range(25, 30)):
        cells[at], tiles[at] = 0, 0
    cells[13], cells[14], cells[17], tiles[16], tiles[17] = 10, 1, 7, 4, 77
    def rows(values):
        return [''.join(f'{n:02x}' for n in values[at:at + 12]) for at in range(0, 240, 12)]
    level = dict(number=1, cells=rows(cells), tiles=rows(tiles), decorations=rows([0] * 240), solution='')
    (profile / 'levels/classic.json').write_text(json.dumps(dict(edition='classic', width=12, height=20,
        levels=[level, dict(level, number=2)]), indent=1) + '\n')
    (profile / 'levels/approved.json').write_text('{"levels":[]}')
    shutil.copyfile(ROOT / 'scripts/editor_check.py', profile / 'scripts/editor_check.py')
    shutil.copyfile(ROOT / 'build/solver/fingerprint', profile / 'build/solver/fingerprint')
    # The board's own search finds the route; every search that continues
    # from played moves finds nothing, as after a crate pushed into a corner.
    real = ROOT / 'build/solver/shovey-solve-classic'
    solver = profile / 'build/solver/shovey-solve-classic'
    solver.write_text('#!/usr/bin/env python3\nimport os,sys\n'
        'args=sys.argv[1:]\n'
        'if "--prefix" in args:print(\'stats {"solved":false,"stop":"time-limit"}\');sys.exit(0)\n'
        f'os.execv({str(real)!r},[{str(real)!r}]+args)\n')
    solver.chmod(0o755)
    driver_folder = profile / 'driver'
    driver_folder.mkdir()
    environment = os.environ | dict(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0',
                                    KRYON_TEST_DRIVER=str(driver_folder))
    with (output / 'app.log').open('w') as log:
        child = subprocess.Popen([str(EDITOR), '1'], cwd=profile, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            def window_id():
                assert child.poll() is None, 'Editor exited'
                return subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                      capture_output=True, text=True).stdout.split()
            window = wait(window_id, 'Editor did not open')[0]
            assert int(subprocess.check_output(['xdotool', 'getwindowpid', window])) == child.pid
            subprocess.run(['xdotool', 'windowfocus', window], check=True)
            driver = Driver(driver_folder)
            def key(name):
                subprocess.run(['xdotool', 'key', name], check=True)
                time.sleep(.2)
            wait(lambda: (drafts / '001.proof').exists(), 'The board search found no route')
            wait(lambda: driver.showing('Winnable'), 'The found route did not show')
            key('Tab')
            key('Down')
            # The continuation from the stray move fails; the board still wins.
            def continued():
                return any((folder / 'finished').exists() and (folder / 'request').read_text().split('\n')[1] == '3'
                           for folder in (profile / 'build/editor').glob('check-*'))
            wait(continued, 'No continuation search ran from the stray move')
            time.sleep(.6)
            labels = driver.labels()
            assert not any('no continuation' in label.lower() or 'no route' in label.lower() for label in labels), labels
            assert any('winnable' in label.lower() for label in labels), labels
            assert not (drafts / '001.check').exists(), 'A failed continuation was saved as the board verdict'
            key('Tab')
            wait(lambda: driver.showing('Winnable'), 'Edit lost the found route')
            time.sleep(1.0)
            labels = driver.labels()
            assert not any('no route' in label.lower() for label in labels), labels
            assert not (drafts / '001.check').exists(), 'A failed continuation was saved as the board verdict'
        finally:
            for directory in (profile / 'build/editor').glob('check-*'):
                (directory / 'cancel').write_text('1')
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
print('Any route counts: a failed continuation after a stray move keeps the board winnable, in play and in Edit')
