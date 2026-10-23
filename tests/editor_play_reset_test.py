"""Entering the private editor's Play view always starts the board again."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
args = parser.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/editor-play-reset-test'
output.mkdir(parents=True, exist_ok=True)


def wait(predicate, message):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(.04)
    raise AssertionError(message)


with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
    profile = Path(temporary)
    drafts = profile / 'backup/editor-drafts'
    for path in (drafts, profile / 'backup/redesign', profile / 'levels',
                 profile / 'scripts', profile / 'build/solver'):
        path.mkdir(parents=True, exist_ok=True)
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
    (profile / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
    (drafts / 'orientation').write_text('portrait')
    cells, tiles = [12] * 240, [12] * 240
    for at in range(13, 19):
        cells[at], tiles[at] = 0, 0
    cells[13], cells[14], cells[18], tiles[17], tiles[18] = 10, 1, 7, 4, 77

    def rows(values):
        return [''.join(f'{n:02x}' for n in values[at:at + 12]) for at in range(0, 240, 12)]

    board = ''.join(rows(cells) + rows(tiles) + rows([0] * 240))
    level = dict(number=1, cells=rows(cells), tiles=rows(tiles), decorations=rows([0] * 240), solution='')
    campaign = json.dumps(dict(edition='classic', width=12, height=20,
                              levels=[level, dict(level, number=2)]), indent=1) + '\n'
    (profile / 'levels/classic.json').write_text(campaign)
    (profile / 'levels/approved.json').write_text('{"levels":[]}')
    (drafts / '001.hex').write_text(board)
    (drafts / '001.attempt').write_text(board + '\n22')
    shutil.copyfile(ROOT / 'scripts/editor_check.py', profile / 'scripts/editor_check.py')
    shutil.copyfile(ROOT / 'build/solver/fingerprint', profile / 'build/solver/fingerprint')
    solver = profile / 'build/solver/shovey-solve-classic'
    solver.write_text('#!/bin/sh\necho \'stats {"solved":false,"stop":"time-limit"}\'\n')
    solver.chmod(0o755)
    driver = profile / 'driver'
    driver.mkdir()
    environment = os.environ | dict(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
                                     YUE_DESKTOP_RECOVERY='0', KRYON_TEST_DRIVER=str(driver))
    with (output / 'app.log').open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve()), '1'], cwd=profile, env=environment,
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            def windows():
                assert child.poll() is None, 'Editor exited'
                return subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                      capture_output=True, text=True).stdout.split()

            window = wait(windows, 'Editor did not open')[0]
            assert int(subprocess.check_output(['xdotool', 'getwindowpid', window])) == child.pid
            subprocess.run(['xdotool', 'windowfocus', window], check=True)

            def key(name):
                subprocess.run(['xdotool', 'key', '--window', window, name], check=True)
                time.sleep(.18)

            def toggle_button():
                subprocess.run(['xdotool', 'mousemove', '--window', window, '572', '28', 'mousedown', '1'], check=True)
                time.sleep(.08)
                subprocess.run(['xdotool', 'mouseup', '1'], check=True)
                time.sleep(.18)

            counter = [0]

            def moves():
                counter[0] += 1
                pending = driver / 'command.new'
                pending.write_text(f'{counter[0]}\ttree\n')
                pending.replace(driver / 'command')
                reply = driver / 'reply'
                wait(reply.exists, 'Editor tree did not respond')
                tree = json.loads(reply.read_text())
                reply.unlink()
                assert tree['ok'], tree
                for node in tree['nodes']:
                    if match := re.search(r'\b(\d+) moves\.', node['label']):
                        return int(match.group(1))

            # Even a checkpoint saved by an earlier process must not resume.
            key('Tab')
            wait(lambda: moves() == 0, 'Initial Play resumed a saved attempt')
            key('Right')
            wait(lambda: moves() == 1, 'The starting move was not recorded')
            for toggle in (lambda: key('Tab'), toggle_button):
                toggle()  # Play -> Edit
                toggle()  # Edit -> Play
                wait(lambda: moves() == 0, 'Returning to Play retained prior moves')
                key('Right')
                wait(lambda: moves() == 1, 'Returning to Play did not restore the starting board')
            assert (drafts / '001.hex').read_text() == board, 'Play changed the authored board'
            assert (profile / 'levels/classic.json').read_text() == campaign, 'Play changed the campaign'
        finally:
            for directory in (profile / 'build/editor').glob('check-*'):
                (directory / 'cancel').write_text('1')
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
print('Editor Play starts fresh for saved attempts, Tab and toolbar re-entry; authored data preserved. No screenshots.')
