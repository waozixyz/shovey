#!/usr/bin/env python3
"""Prove the relay/paint workshop and the colour-cycle ice pavilion.

The counterfactual searches isolate real dependencies: the workshop needs a
ball to relay its pressure plate, and its paint order needs the side buffer.
For the pavilion, exact single-block searches on an ice-free relaxation prove
that colour phases add pushes beyond travel distance. No walking-length score
is used as evidence of puzzle difficulty.
"""
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess

from classic_difficulty_test import cells, independent_pushes
from classic_63_65_68_test import data, explain, rows

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'
BLOCKS = {36, 37, 38, 53, 54, 55}
GOALS = {39, 143, 145, 147}


def search(level, method='bfs', impossible=False, prefix='', seconds=12):
    command = [str(SOLVER), 'solve', '--level', str(level['number']), '--only', method,
               '--seconds', str(seconds), '--max-states', '1200000', '--max-mb', '96']
    if prefix:
        command += ['--prefix', prefix]
    result = subprocess.run(command + [data(level)], capture_output=True, text=True,
                            timeout=seconds + 10)
    if impossible:
        assert result.returncode == 1 and '"stop":"exhausted"' in result.stderr, result.stderr
        return None
    assert result.returncode == 0, (level['number'], result.stderr)
    return explain(level, result.stdout.strip())


def workshop(level):
    board, terrain = cells(level['cells']), cells(level['tiles'])
    assert board.count(9) == board.count(18) == 2 and board.count(3) == 3
    assert board.count(13) == board.count(15) == board.count(16) == 1
    assert terrain.count(14) == terrain.count(4) == terrain.count(5) == terrain.count(6) == 1
    proof = explain(level, level['solution'])
    assert proof['goals'] == 5 and proof['used_features'] & 107 == 107
    plate = [event for event in proof['events'] if event['target'] == 13 and event['piece']]
    assert plate[0]['piece'] == 9 and plate[1]['piece'] == 3
    assert plate[0]['destination'] == plate[1]['destination']
    crate_goals = [event for event in proof['events'] if event['piece'] == 9 and event['target'] == 18]
    assert crate_goals[0]['step'] < plate[1]['step'] < crate_goals[-1]['step']
    painting = [event for event in proof['events'] if event['features'] & 32]
    assert [event['target'] for event in painting] == [15, 16]
    assert painting[0]['piece_id'] != painting[1]['piece_id']
    # A fresh native search plans the unresolved colour stage after the proven
    # relay opening; the complete source route is independently replayed above.
    fresh = search(level, 'greedy', prefix=level['solution'][:crate_goals[-1]['step']], seconds=40)
    assert fresh['goals'] == 5
    # Even with paint removed, two crates cannot both cross the sluice unless
    # another movable object takes over the external pressure plate.
    no_relay = dict(level, cells=rows([0 if kind in (3, 15, 16) else kind for kind in board]))
    search(no_relay, impossible=True)
    # Clear the entire crate objective and the third ball: the two-colour
    # relaxation still cannot work if the mandatory side buffer is sealed.
    relaxed = [0 if kind in (9, 18, 13) else kind for kind in board]
    relaxed[plate[1]['piece_id']] = 0
    floor = [100 if kind in (6, 14) else kind for kind in terrain]
    two_balls = dict(level, cells=rows(relaxed), tiles=rows(floor))
    search(two_balls, 'macro-bfs')
    first_red = painting[0]
    staged = next(event for event in proof['events'] if event['step'] > first_red['step']
                  and event['piece_id'] == first_red['piece_id'])
    y, turned_x = staged['destination']
    buffer = y * 12 + 11 - turned_x
    assert board[buffer] == 0
    floor[buffer] = 96
    search(dict(two_balls, tiles=rows(floor)), impossible=True)
    print('Classic 73: native win; crate-to-ball pressure relay and ordered paint buffer are mandatory', flush=True)


def pavilion(level):
    board, terrain = cells(level['cells']), cells(level['tiles'])
    pieces = [at for at, kind in enumerate(board) if kind in BLOCKS]
    goals = [at for at, kind in enumerate(board) if kind in GOALS]
    assert len(pieces) == len(goals) == 4
    assert sum(board[at] < 39 for at in pieces) == 2 and terrain.count(70) >= 25
    assert not board.count(9) and not board.count(19)
    proof = explain(level, level['solution'])
    assert proof['goals'] == 4 and proof['used_features'] & 128
    # This opening deliberately reaches the wrong phases at the goal positions;
    # the native solver must then find the colour correction and return home.
    search(level, 'greedy', prefix=level['solution'][:70], seconds=40)
    plain = [99 if kind == 70 else kind for kind in terrain]
    costs = []
    for piece in pieces:
        row = []
        for goal in goals:
            family = 36 if board[piece] < 39 else 53
            if (board[goal] == 143 and family == 53 or board[goal] in (145, 147) and family == 36):
                row.append(math.inf)
                continue
            single = [kind if (kind not in BLOCKS or at == piece) and
                      (kind not in GOALS or at == goal) else 0 for at, kind in enumerate(board)]
            result = search(dict(level, cells=rows(single), tiles=rows(plain)), 'macro-bfs', seconds=3)
            row.append(result['pushes'])
        costs.append(row)
    phase_minimum = min(sum(costs[i][j] for i, j in enumerate(order))
                        for order in itertools.permutations(range(4)))
    ordinary = [9 if kind in BLOCKS else 18 if kind in GOALS else kind for kind in board]
    distance = independent_pushes(ordinary, plain)
    assert phase_minimum >= 34 and phase_minimum - distance >= 12, (phase_minimum, distance)
    print(f'Classic 74: native ice/colour win; even without ice, {phase_minimum} independent pushes '
          f'are required, {phase_minimum - distance} forced by colour phases', flush=True)


def main():
    digest = hashlib.sha256()
    for name in ('tools/solver/solver.c', 'tools/solver/classic_api.zi',
                 'src/solver/classic_deadlocks.zi', 'src/engine.zi'):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    assert (ROOT / 'build/solver/fingerprint').read_text().strip() == digest.hexdigest(), 'Run make solver first'
    approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    private = ROOT / 'levels/classic.json'
    classic = json.loads(private.read_text())['levels'] if private.exists() else approved
    for number in (73, 74):
        assert approved[number - 1] == classic[number - 1], (number, 'campaign copies differ')
        assert cells(approved[number - 1]['cells']).count(10) == 1
    workshop(approved[72])
    pavilion(approved[73])


if __name__ == '__main__':
    main()
