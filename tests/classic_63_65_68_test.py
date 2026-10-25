#!/usr/bin/env python3
"""Prove the redesigned crate rooms and their colour/pressure objectives.

For the colour boards, also solve a relaxation with the ball, paint and pit
removed. Compare its push optimum with an optimal assignment of independently
solved single-crate boards. The gap proves that the crates interfere even when
the colour objective is already cleared; extra walking cannot create that gap.
Every search and replay uses the shipped game engine.
"""
import itertools
import json
import math
from pathlib import Path
import subprocess

from classic_difficulty_test import cells

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'


def rows(board):
    return [''.join(f'{kind:02x}' for kind in board[at:at + 12])
            for at in range(0, 240, 12)]


def data(level):
    return ''.join(''.join(level[key]) for key in ('cells', 'tiles', 'decorations'))


def explain(level, route):
    replay = subprocess.run([str(SOLVER), 'explain', '--level', str(level['number']),
                             data(level), route], capture_output=True, text=True,
                            timeout=10)
    assert replay.returncode == 0, (level['number'], replay.stderr)
    proof = json.loads(replay.stdout)
    assert not proof['events_truncated']
    return proof


def solve(level, method, single=False, unsolvable=False):
    result = subprocess.run(
        [str(SOLVER), 'solve', '--level', str(level['number']), '--only', method,
         '--seconds', '5' if single else '90',
         '--max-states', '10000' if single else '2500000',
         '--max-mb', '32' if single else '192', data(level)],
        capture_output=True, text=True, timeout=10 if single else 100)
    if unsolvable and result.returncode == 1:
        assert '"stop":"exhausted"' in result.stderr, result.stderr
        return None
    assert result.returncode == 0, (level['number'], result.stderr)
    return explain(level, result.stdout.strip())


def independent_assignment(level):
    board = cells(level['cells'])
    crates = [at for at, kind in enumerate(board) if kind == 9]
    goals = [at for at, kind in enumerate(board) if kind == 18]
    costs = []
    for crate in crates:
        costs.append([])
        for goal in goals:
            single = [kind if (kind != 9 or at == crate) and
                      (kind != 18 or at == goal) else 0
                      for at, kind in enumerate(board)]
            proof = solve(dict(level, cells=rows(single)), 'macro-bfs',
                          single=True, unsolvable=True)
            costs[-1].append(proof['crate_pushes'] if proof else math.inf)
    return min(sum(costs[crate][goal] for crate, goal in enumerate(order))
               for order in itertools.permutations(range(len(goals))))


def main():
    approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    private = ROOT / 'levels/classic.json'
    classic = json.loads(private.read_text())['levels'] if private.exists() else approved
    # Measured optima of the authored layouts, with the colour objective cleared.
    colour_rooms = {63: (16, 5, 28, 22), 68: (15, 4, 21, 17)}
    for number in (63, 65, 68):
        level = approved[number - 1]
        assert level == classic[number - 1], f'Classic {number}: campaign copies differ'
        board = cells(level['cells'])
        assert set(board) <= {0, 3, 4, 5, 7, 9, 10, 13, 14, 15, 16, 18}
        assert set(cells(level['tiles'])) <= {0, 12, 78, 95, 96, 99, 100}
        assert set(cells(level['decorations'])) <= {0, 135, 136, 137}
        assert board.count(9) == 4 and board.count(10) == board.count(7) == 1
        stored = explain(level, level['solution'])
        fresh = solve(level, 'macro-bfs' if number == 65 else 'greedy')
        assert stored['goals'] == fresh['goals'] == (3 if number == 65 else 5)
        assert len({event['piece_id'] for event in fresh['events']
                    if event['piece'] == 9}) == 4
        if number == 65:
            assert fresh['crate_pushes'] == fresh['pushes'] == 22
            # A crate must hold the plate and another must enter the gated room.
            assert fresh['used_features'] & 72 == 72
            plate = next(event['step'] for event in fresh['events'] if event['features'] & 64)
            crossing = next(event['step'] for event in fresh['events'] if event['features'] & 8)
            assert plate < crossing
            sealed = [12 if kind == 13 else kind for kind in board]
            assert solve(dict(level, cells=rows(sealed)), 'macro-bfs',
                         unsolvable=True) is None
            print('Classic 65: 22 minimum pushes; plate and gated delivery required', flush=True)
            continue
        paint, pit, minimum, independent = colour_rooms[number]
        assert board.count(18) == 4 and board.count(3) == 1
        assert board.count(paint) == board.count(pit) == 1
        assert fresh['used_features'] & 32
        unpainted = [0 if kind == paint else kind for kind in board]
        assert solve(dict(level, cells=rows(unpainted)), 'macro-bfs',
                     unsolvable=True) is None
        relaxed = dict(level, cells=rows([0 if kind in (3, paint, pit) else kind
                                         for kind in board]))
        optimum = solve(relaxed, 'macro-bfs')
        assert optimum['pushes'] == optimum['crate_pushes'] == minimum
        assert independent_assignment(relaxed) == independent < minimum
        print(f'Classic {number}: colour objective required; {minimum} minimum crate '
              f'pushes even after clearing it, {minimum - independent} caused by '
              'crate interaction', flush=True)


if __name__ == '__main__':
    main()
