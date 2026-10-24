"""The private editor's memory stays flat while it rereads its files.

Every change of the publication status makes the editor reread the approved
campaign and every place's markers. Native Ziran keeps the text that
ReadEntireFile returns for the life of the program, so each reread used to
add the whole campaign to the editor's memory, about 1.4 MB a time, until it
froze. This runs the editor on a private display with a full campaign, keeps
changing the status for half a minute and checks the resident set barely grows.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--seconds', type=float, default=30.0)
args = parser.parse_args()
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/editor-memory-test'
output.mkdir(parents=True, exist_ok=True)


def resident(pid):
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) // 1024
    raise AssertionError('Editor exited')


with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
    profile = Path(temporary)
    drafts = profile / 'backup/editor-drafts'
    for path in (drafts, profile / 'backup/redesign', profile / 'levels', profile / 'scripts', profile / 'build/solver'):
        path.mkdir(parents=True, exist_ok=True)
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
    # The published campaign stands in for the private level file.
    campaign = (ROOT / 'levels/approved.json').read_text()
    (profile / 'levels/classic.json').write_text(campaign)
    (profile / 'levels/approved.json').write_text(campaign)
    (profile / 'backup/redesign/stuck.txt').write_text('')
    (drafts / 'orientation').write_text('portrait')
    shutil.copyfile(ROOT / 'build/solver/fingerprint', profile / 'build/solver/fingerprint')
    solver = profile / 'build/solver/shovey-solve-classic'
    solver.write_text('#!/bin/sh\necho \'stats {"solved":false,"stop":"time-limit"}\'\n')
    solver.chmod(0o755)
    environment = os.environ | dict(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
    with (output / 'app.log').open('w') as log:
        child = subprocess.Popen([str(args.binary.resolve()), '1'], cwd=profile, env=environment,
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while not subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                     capture_output=True).stdout.strip():
                assert child.poll() is None and time.monotonic() < deadline, 'Editor did not open'
                time.sleep(.1)
            time.sleep(3)
            start = resident(child.pid)
            changes = 0
            end_at = time.monotonic() + args.seconds
            while time.monotonic() < end_at:
                changes += 1
                status = drafts / 'publish-status.new'
                status.write_text(f'Level 1: checking · {changes} queued')
                status.replace(drafts / 'publish-status')
                time.sleep(.25)
            time.sleep(1)
            growth = resident(child.pid) - start
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
assert growth < 8, f'Editor memory grew {growth} MB over {changes} status changes'
print(f'Editor memory grew {growth} MB over {changes} status changes with the full campaign. No screenshots.')
