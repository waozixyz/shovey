#!/usr/bin/env python3
"""Prove distinct switch, phase, bridge, ice and paint puzzles through the engine."""
import json
from pathlib import Path
import subprocess

from classic_difficulty_test import cells
from classic_63_65_68_test import data, explain, rows

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'


def search(level, method='bfs', prefix=None, impossible=False):
    command = [str(SOLVER), 'solve', '--level', str(level['number']), '--only', method,
               '--seconds', '40', '--max-states', '1500000', '--max-mb', '128']
    if prefix is not None:
        command += ['--prefix', prefix]
    result = subprocess.run(command + [data(level)], capture_output=True, text=True, timeout=50)
    if impossible:
        assert result.returncode == 1 and '"stop":"exhausted"' in result.stderr, result.stderr
        return None
    assert result.returncode == 0, (level['number'], result.stderr)
    return result.stdout.strip(), explain(level, result.stdout.strip())


def main():
    approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    private = ROOT / 'levels/classic.json'
    classic = json.loads(private.read_text())['levels'] if private.exists() else approved
    for number in (55, 56, 64, 65, 68):
        level = approved[number - 1]
        assert level == classic[number - 1], (number, 'campaign copies differ')
        board, terrain = cells(level['cells']), cells(level['tiles'])
        assert board.count(10) == board.count(7) == 1
        assert set(cells(level['decorations'])) <= {0, 135, 137, 138}
        stored = explain(level, level['solution'])
        route, proof = search(level, 'bfs' if number in (64, 65) else 'macro-bfs')
        assert stored['goals'] == proof['goals']
        assert not proof['events_truncated']
        if number == 55:
            assert board.count(93) == 2 and board.count(92) == board.count(123) == 1
            assert not board.count(9) and proof['goals'] == 3
            assert proof['ball_pushes'] == 18 and proof['used_features'] & 24 == 24
            assert sum(bool(event['features'] & 16) for event in proof['events']) == 3
            sealed = list(board)
            sealed[9 * 12 + 2] = 0
            search(dict(level, cells=rows(sealed)), impossible=True)
            print('Classic 55: two switch stations and three gate-state changes required', flush=True)
        elif number == 56:
            assert board.count(36) == board.count(53) == board.count(143) == board.count(147) == 1
            assert not board.count(9) and proof['goals'] == 2 and proof['pushes'] == 27
            # Distinct colour families must exchange rooms. Each push cycles
            # its colour; parity and phase force six pushes beyond distance.
            distance = minimum = 0
            for piece, goal, phase in ((36, 143, 1), (53, 147, 2)):
                start, end = board.index(piece), board.index(goal)
                span = abs(start % 12 - end % 12) + abs(start // 12 - end // 12)
                cost = span
                while cost % 3 != phase or cost % 2 != span % 2:
                    cost += 1
                distance += span
                minimum += cost
            assert minimum == proof['pushes'] == distance + 6
            sealed = list(terrain)
            sealed[8 * 12 + 5] = 98
            search(dict(level, tiles=rows(sealed)), impossible=True)
            print('Classic 56: opposite-room colour families need 27 phase-correct pushes', flush=True)
        elif number == 64:
            assert board.count(21) == proof['goals'] == 7 and board.count(71) + terrain.count(71) == 14
            assert not proof['pushes'] and proof['moves'] == 57
            # Taking the left bridge first strands the last apple/return path.
            search(level, prefix='223330333', impossible=True)
            print('Classic 64: seven pickups across one-use bridges; wrong first crossing loses the route', flush=True)
        elif number == 65:
            assert board.count(9) == board.count(18) == 2 and proof['goals'] == 3
            assert proof['moves'] == 37 and proof['used_features'] & 128
            slippery = list(terrain)
            for x, y in ((2, 4), (8, 5), (4, 10), (7, 9)):
                assert slippery[y * 12 + x] == 100
                slippery[y * 12 + x] = 70
            search(dict(level, tiles=rows(slippery)), impossible=True)
            print('Classic 65: icy approaches, stopping pads and movable brakes; 37 accepted inputs', flush=True)
        else:
            assert board.count(3) == board.count(44) == board.count(15) == board.count(16) == 1
            assert not board.count(9) and proof['goals'] == 2 and proof['ball_pushes'] == 27
            painting = [event for event in proof['events'] if event['features'] & 32]
            assert [event['target'] for event in painting] == [15, 16]
            assert painting[0]['piece_id'] != painting[1]['piece_id']
            red_finish = next(event for event in proof['events'] if event['target'] == 4)
            assert red_finish['piece_id'] == painting[0]['piece_id']
            assert red_finish['step'] > painting[1]['step']
            # Sending the first ball straight on spends both paints and
            # leaves no colour for the second. The side buffer is essential.
            search(level, prefix=route[:painting[0]['step']] + '333', impossible=True)
            print('Classic 68: first painted ball must wait in the buffer for the second paint to be spent', flush=True)


if __name__ == '__main__':
    main()
