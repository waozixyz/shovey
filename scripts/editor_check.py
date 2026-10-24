#!/usr/bin/env python3
"""Run one editor checkpoint's searches; cancel only children we started."""
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SEARCHES = ('greedy', 'macro-bfs', 'chain', 'bfs')
# While the owner plays, a continuation search runs beside the game: two
# searches, at the lowest priority, on the cores kept for background work,
# so the editor stays smooth.
LIVE_SEARCHES = ('greedy', 'chain')
BACKGROUND = ['taskset', '-c', '2-5,10-15', 'nice', '-n', '19']


def run(directory, root=ROOT):
    directory = Path(directory).resolve()
    root = Path(root).resolve()
    if directory.parent != root / 'build/editor' or not re.fullmatch(r'check-\d+-\d+', directory.name):
        raise ValueError('Invalid editor check directory')
    board, prefix, level, seconds, mode = (directory / 'request').read_text().splitlines()
    if not re.fullmatch('[0-9a-f]{1440}', board) or not re.fullmatch('[0123ft]{0,60000}', prefix):
        raise ValueError('Invalid checkpoint')
    if not level.isdigit() or not 0 <= int(level) <= 200 or not seconds.isdigit() or not 1 <= int(seconds) <= 120:
        raise ValueError('Invalid solver limits')
    if mode not in ('live', 'repair'):
        raise ValueError('Invalid checkpoint mode')
    cancelled = False

    def cancel(unused_signum, unused_frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    children = []
    try:
        for index, name in enumerate(SEARCHES):
            if cancelled or (directory / 'cancel').exists():
                break
            if mode == 'live' and name not in LIVE_SEARCHES:
                (directory / (name + '.out')).write_text('')
                continue
            command = BACKGROUND + [str(root / 'build/solver/shovey-solve-classic'), 'solve', '--level', level,
                       '--seconds', seconds, '--max-mb', '128', '--only', name]
            if prefix:
                if mode == 'live':
                    command += ['--prefix', prefix]
                elif index in (0, 2):
                    part = len(prefix) if index == 0 else len(prefix) - 16 if len(prefix) > 16 else (len(prefix) + 1) // 2
                    command += ['--repair', prefix[:part]]
            command += [board]
            stream = (directory / (name + '.tmp')).open('w')
            child = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            children.append((name, child, stream))
        remaining = set(range(len(children)))
        while remaining and not cancelled and not (directory / 'cancel').exists():
            for index in list(remaining):
                name, child, stream = children[index]
                if child.poll() is not None:
                    stream.close()
                    (directory / (name + '.tmp')).replace(directory / (name + '.out'))
                    remaining.remove(index)
            if remaining:
                time.sleep(.05)
    finally:
        # Popen objects refer only to this coordinator's own children. No
        # shared PID files, process-name killing or foreign process groups.
        for unused_name, child, stream in children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
            stream.close()
        (directory / 'finished').write_text('cancelled' if cancelled or (directory / 'cancel').exists() else 'done')


if __name__ == '__main__':
    run(sys.argv[1])
