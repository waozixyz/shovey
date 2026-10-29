#!/usr/bin/env python3
"""Preserve Classic 63's crate/colour proof across terrain layer placement.

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
    colour_rooms = {63: (16, 5, 28, 22)}
    for number in (63,):
        level = approved[number - 1]
        def logical_layers(value):
            pieces, terrain = cells(value['cells']), cells(value['tiles'])
            for at, kind in enumerate(pieces):
                if kind in (4, 5, 6):
                    pieces[at], terrain[at] = 0, kind
            return pieces, terrain, cells(value['decorations']), value['solution']
        assert logical_layers(level) == logical_layers(classic[number - 1]), \
            f'Classic {number}: gameplay copies differ'
        board = cells(level['cells'])
        assert set(board) <= {0, 3, 4, 5, 7, 9, 10, 13, 14, 15, 16, 18}
        assert set(cells(level['tiles'])) <= {0, 5, 12, 77, 78, 95, 96, 97, 98, 99, 100, 101, 102, 162, 163, 164}
        assert set(cells(level['decorations'])) <= {0, 59, 135, 136, 137, 161} | {84, 106, 122, 139, 140, 141, 142, 158, 159, 160, 165}
        assert board.count(9) == 4 and board.count(10) == board.count(7) == 1
        stored = explain(level, level['solution'])
        fresh = solve(level, 'greedy')
        assert stored['goals'] == fresh['goals'] == 5
        assert len({event['piece_id'] for event in fresh['events']
                    if event['piece'] == 9}) == 4
        paint, pit, minimum, independent = colour_rooms[number]
        assert board.count(18) == 4 and board.count(3) == 1
        terrain = cells(level['tiles'])
        assert board.count(paint) == board.count(pit) + terrain.count(pit) == 1
        assert fresh['used_features'] & 32
        unpainted = [0 if kind == paint else kind for kind in board]
        assert solve(dict(level, cells=rows(unpainted)), 'macro-bfs',
                     unsolvable=True) is None
        relaxed = dict(level, cells=rows([0 if kind in (3, paint, pit) else kind
                                         for kind in board]),
                       tiles=rows([0 if kind == pit else kind for kind in terrain]))
        optimum = solve(relaxed, 'macro-bfs')
        assert optimum['pushes'] == optimum['crate_pushes'] == minimum
        assert independent_assignment(relaxed) == independent < minimum
        print(f'Classic {number}: colour objective required; {minimum} minimum crate '
              f'pushes even after clearing it, {minimum - independent} caused by '
              'crate interaction', flush=True)


if __name__ == '__main__':
    main()
