"""Continue from manual play, recalculate after undo, and keep AI replay separate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
assert int(os.environ['DISPLAY'].split(':')[-1].split('.')[0]) >= 400
output = ROOT / 'build/editor-live-play-test'
output.mkdir(parents=True, exist_ok=True)


def wait(predicate, message):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(.04)
    raise AssertionError(message)


with tempfile.TemporaryDirectory(prefix='profile-', dir=output) as temporary:
    profile = Path(temporary)
    drafts = profile / 'backup/editor-drafts'
    for path in (drafts, profile / 'backup/redesign', profile / 'levels', profile / 'scripts', profile / 'build/solver'):
        path.mkdir(parents=True, exist_ok=True)
    (profile / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
    (profile / 'backup/redesign/stuck.txt').write_text(''.join(f'classic {n}\n' for n in range(2, 175)))
    (drafts / 'orientation').write_text('portrait')
    cells, tiles = [12] * 240, [12] * 240
    for at in range(13, 18):
        cells[at], tiles[at] = 0, 0
    cells[13], cells[14], cells[17], tiles[16], tiles[17] = 10, 1, 7, 4, 77
    cells[15], tiles[15] = 103, 103
    def rows(values):
        return [''.join(f'{n:02x}' for n in values[at:at + 12]) for at in range(0, 240, 12)]
    level = dict(number=1, cells=rows(cells), tiles=rows(tiles), decorations=rows([0] * 240), solution='')
    (profile / 'levels/classic.json').write_text(json.dumps(dict(edition='classic', width=12, height=20,
        levels=[level, dict(level, number=2)]), indent=1) + '\n')
    (profile / 'levels/approved.json').write_text('{"levels":[]}')
    shutil.copyfile(ROOT / 'scripts/editor_check.py', profile / 'scripts/editor_check.py')
    shutil.copyfile(ROOT / 'build/solver/fingerprint', profile / 'build/solver/fingerprint')
    solver = profile / 'build/solver/shovey-solve-classic'
    # The first bounded search fails. Exact manual checkpoints then go to
    # the real engine, demonstrating learning rather than a fresh search.
    solver.write_text('#!/usr/bin/env python3\nimport fcntl,json,os,sys\n'
        'args=sys.argv[1:]\nprefix=args[args.index("--prefix")+1] if "--prefix" in args else ""\n'
        'with open("searches.jsonl","a") as log:\n'
        ' fcntl.flock(log,fcntl.LOCK_EX);log.write(json.dumps(dict(prefix=prefix,args=args))+"\\n")\n'
        f'if prefix:os.execv({str(ROOT / "build/solver/shovey-solve-classic")!r},[{str(ROOT / "build/solver/shovey-solve-classic")!r}]+args)\n'
        'print(\'stats {"solved":false,"stop":"time-limit"}\')\n')
    solver.chmod(0o755)
    environment = os.environ | dict(SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy', YUE_DESKTOP_RECOVERY='0')
    with (output / 'app.log').open('w') as log:
        child = subprocess.Popen([str(ROOT / 'build/private-editor/shovey-level-editor'), '1'],
                                 cwd=profile, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            def window_id():
                assert child.poll() is None, 'Editor exited'
                return subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(child.pid)],
                                      capture_output=True, text=True).stdout.split()
            window = wait(window_id, 'Editor did not open')[0]
            assert int(subprocess.check_output(['xdotool', 'getwindowpid', window])) == child.pid
            subprocess.run(['xdotool', 'windowfocus', window], check=True)
            def key(name):
                subprocess.run(['xdotool', 'key', name], check=True)
                time.sleep(.15)
            def attempt():
                path = drafts / '001.attempt'
                lines = path.read_text().splitlines() if path.exists() else []
                return lines[1] if len(lines) > 1 else ''
            def searched(prefix):
                path = profile / 'searches.jsonl'
                return path.exists() and any(json.loads(line)['prefix'] == prefix for line in path.read_text().splitlines())
            wait(lambda: searched(''), 'Initial bounded search did not run')
            assert not (drafts / '001.proof').exists()
            key('Tab')
            key('Right')
            wait(lambda: attempt() == '2', 'Manual opening was not saved')
            wait(lambda: searched('2'), 'The solver ignored the manual opening')
            proof = wait(lambda: (drafts / '001.proof').read_text() if (drafts / '001.proof').exists() else '',
                         'No continuation was found')
            board, route = proof.splitlines()
            assert board[30:32] == '67', 'Loading converted legacy ground into a cosmetic tile'
            assert route.startswith('2')
            subprocess.run([str(ROOT / 'build/solver/shovey-solve-classic'), 'verify', '--level', '1', board, route],
                           check=True, capture_output=True)
            assert attempt() == '2', 'Solver moved the player'
            key('Left')
            wait(lambda: attempt() == '20', 'New move was not saved')
            wait(lambda: searched('20'), 'A prior proof prevented recalculation')
            key('z')
            wait(lambda: attempt() == '2', 'Undo did not update the checkpoint')
            wait(lambda: (drafts / '001.proof').read_text().splitlines()[1].startswith('2'),
                 'Undo could not reuse its matching demonstrated state')
            key('Tab')
            key('Tab')
            key('Right')
            wait(lambda: attempt() == '22', 'Play did not resume the saved partial attempt')
            key('Tab')
            # Replay is not a manual demonstration and must not replace it.
            saved = (drafts / '001.attempt').read_bytes()
            subprocess.run(['xdotool', 'mousemove', '--window', window, '810', '28', 'click', '1'], check=True)
            time.sleep(.8)
            assert (drafts / '001.attempt').read_bytes() == saved, 'AI replay overwrote manual learning'
            key('Tab')
            # A tool can save a draft without touching the campaign JSON.
            # It must appear without reopening the level or application.
            original_board = (drafts / '001.attempt').read_text().splitlines()[0]
            def decorated(board, kind):
                at = 960 + 15 * 2
                return board[:at] + f'{kind:02x}' + board[at + 2:]
            def external_draft(board):
                temporary = drafts / '001.hex.new'
                temporary.write_text(board)
                temporary.replace(drafts / '001.hex')
            updated = decorated(original_board, 57)
            external_draft(updated)
            time.sleep(1.5)
            key('Tab')
            key('Right')
            wait(lambda: (drafts / '001.attempt').read_text().splitlines() == [updated, '2'],
                 'Draft-only changes did not appear live in the editor')
            # Further authoring cannot reset a live demonstration. Returning
            # to Edit adopts the latest board and starts its own attempt.
            next_board = decorated(updated, 58)
            external_draft(next_board)
            time.sleep(1.5)
            key('Right')
            assert (drafts / '001.attempt').read_text().splitlines() == [updated, '22'], 'External update reset manual play'
            key('Tab')
            time.sleep(1.5)
            key('Tab')
            key('Right')
            wait(lambda: (drafts / '001.attempt').read_text().splitlines() == [next_board, '2'],
                 'Edit did not adopt the pending authoring update')
            # Campaign-only saves are followed as well. A stale draft can no
            # longer cover this update once the author removes that draft.
            key('Tab')
            latest = decorated(next_board, 135)
            campaign = json.loads((profile / 'levels/classic.json').read_text())
            campaign['levels'][0]['decorations'] = rows([int(latest[at:at + 2], 16) for at in range(960, 1440, 2)])
            temporary = profile / 'levels/classic.json.new'
            temporary.write_text(json.dumps(campaign, indent=1) + '\n')
            temporary.replace(profile / 'levels/classic.json')
            (drafts / '001.hex').unlink(missing_ok=True)
            time.sleep(1.5)
            key('Tab')
            key('Right')
            wait(lambda: (drafts / '001.attempt').read_text().splitlines() == [latest, '2'],
                 'Campaign-only changes did not appear live')
            subprocess.run(['import', '-window', window, str(output / 'learning.png')], check=True)
        finally:
            for directory in (profile / 'build/editor').glob('check-*'):
                (directory / 'cancel').write_text('1')
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
print('Live play: opening, continuation, undo, resume, replay isolation and live draft/campaign refresh passed')
