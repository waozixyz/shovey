#!/usr/bin/env python3
"""Prove the redesigned rooms require coordination, beyond crate travel.

All searches and route replays use the native game engine. Macro BFS is
push-optimal here: the only state-changing actions are single piece pushes.
For each room, compare the crate optimum with an assignment of independently
solved single-crate boards. That gap cannot come from extra walking.
"""
import hashlib
import itertools
import json
from pathlib import Path
import subprocess

from classic_difficulty_test import cells
from classic_63_65_68_test import data, explain, independent_assignment, rows

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'


def search(level, impossible=False):
    result = subprocess.run(
        [str(SOLVER), 'solve', '--level', str(level['number']), '--only', 'macro-bfs',
         '--seconds', '30', '--max-states', '1000000', '--max-mb', '96', data(level)],
        capture_output=True, text=True, timeout=40)
    if impossible:
        assert result.returncode == 1 and '"stop":"exhausted"' in result.stderr, result.stderr
        return None
    assert result.returncode == 0, (level['number'], result.stderr)
    return explain(level, result.stdout.strip())


def main():
    digest = hashlib.sha256()
    for name in ('tools/solver/solver.c', 'tools/solver/classic_api.zi',
                 'src/solver/classic_deadlocks.zi', 'src/engine.zi'):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    assert (ROOT / 'build/solver/fingerprint').read_text().strip() == digest.hexdigest(), \
        'Native solver is stale; run make solver first'
    approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    private = ROOT / 'levels/classic.json'
    classic = json.loads(private.read_text())['levels'] if private.exists() else approved
    for number, minimum, detour in ((73, 35, 10), (74, 30, 6)):
        level = approved[number - 1]
        assert level == classic[number - 1], (number, 'campaign copies differ')
        board, terrain = cells(level['cells']), cells(level['tiles'])
        assert board.count(10) == board.count(7) == 1
        assert board.count(9) == board.count(18) == 4
        assert set(board) <= ({0, 2, 7, 9, 10, 15, 18} if number == 73 else {0, 7, 9, 10, 18})
        assert set(terrain) <= {4, 77, 95, 96, 99, 100}
        # Scenery must leave the ordinary push proof applicable.
        assert set(cells(level['decorations'])) <= {0, 135, 136, 137}
        stored = explain(level, level['solution'])
        fresh = search(level)
        assert fresh['goals'] == stored['goals'] == (5 if number == 73 else 4)
        pushes = [event for event in fresh['events'] if event['piece'] == 9]
        assert len({event['piece_id'] for event in pushes}) == 4
        switches = sum(a['piece_id'] != b['piece_id'] for a, b in zip(pushes, pushes[1:]))
        assert switches >= 8, (number, 'crates no longer need interleaving')
        if number == 73:
            assert board.count(2) == board.count(15) == terrain.count(4) == 1
            assert fresh['ball_pushes'] >= 2 and fresh['used_features'] & 32
            ball = [event for event in fresh['events'] if event['piece'] in (1, 2)]
            assert pushes[0]['step'] < ball[0]['step'], 'The ball approach must be cleared first'
            # The red paint is necessary; a blue ball cannot clear the red pit.
            unpainted = dict(level, cells=rows([0 if kind == 15 else kind for kind in board]))
            search(unpainted, impossible=True)
            relaxed = dict(level,
                           cells=rows([0 if kind in (2, 15) else kind for kind in board]),
                           tiles=rows([100 if kind == 4 else kind for kind in terrain]))
            optimum = search(relaxed)
        else:
            crates = [at for at, kind in enumerate(board) if kind == 9]
            goals = [at for at, kind in enumerate(board) if kind == 18]
            distance = lambda a, b: abs(a % 12 - b % 12) + abs(a // 12 - b // 12)
            assert all(distance(a, b) >= 2 for a, b in itertools.combinations(crates, 2))
            assert all(distance(a, b) >= 2 for a in crates for b in goals)
            relaxed, optimum = level, fresh
        assert optimum['pushes'] == optimum['crate_pushes'] >= minimum
        independent = independent_assignment(relaxed)
        extra = optimum['crate_pushes'] - independent
        assert extra >= detour, (number, optimum['crate_pushes'], independent)
        print(f'Classic {number}: fresh engine solution, {fresh["moves"]} moves, '
              f'{fresh["pushes"]} minimum pushes; {extra} required crate-interaction pushes',
              flush=True)


if __name__ == '__main__':
    main()
