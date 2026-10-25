#!/usr/bin/env python3
"""Keep Classic 54–57 solvable and dependent on coordinated crate pushes.

The existing solver's macro BFS is push-optimal on these ordinary Sokoban
boards: walking is free and each macro edge is one crate push. Compare that
minimum with independent crate-to-goal distances to catch layouts that are
long only because the goals are far away. Build with `make solver` first.
"""
import itertools
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'
WIDTH, HEIGHT = 12, 20
WALLS = {12, 95, 96, 97, 98}


def cells(rows):
    text = ''.join(rows)
    assert len(rows) == HEIGHT and all(len(row) == WIDTH * 2 for row in rows)
    return [int(text[at:at + 2], 16) for at in range(0, len(text), 2)]


def neighbor(at, direction):
    x, y = at % WIDTH, at // WIDTH
    dx, dy = ((-1, 0), (0, -1), (1, 0), (0, 1))[direction]
    x, y = x + dx, y + dy
    return y * WIDTH + x if 0 <= x < WIDTH and 0 <= y < HEIGHT else -1


def independent_pushes(board, tiles):
    """Minimum assignment cost with walls/standing space, ignoring other crates."""
    room = {board.index(10)}
    pending = list(room)
    for at in pending:
        for direction in range(4):
            to = neighbor(at, direction)
            if to >= 0 and to not in room and tiles[to] not in WALLS:
                room.add(to)
                pending.append(to)
    crates = [at for at in room if board[at] == 9]
    goals = [at for at in room if board[at] == 18]
    distances = []
    for goal in goals:
        distance = {goal: 0}
        pending = [goal]
        for at in pending:
            for direction in range(4):
                before = neighbor(at, direction)
                support = neighbor(before, direction) if before >= 0 else -1
                if before in room and support in room and before not in distance:
                    distance[before] = distance[at] + 1
                    pending.append(before)
        distances.append(distance)
    assert len(crates) == board.count(9) == len(goals) == board.count(18)
    cost = min(sum(distance.get(crate, 10000) for distance, crate in zip(distances, order))
               for order in itertools.permutations(crates))
    assert cost < 10000, 'Every crate must have an individual path to a mark'
    return cost


def main():
    approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    private = ROOT / 'levels/classic.json'
    classic = json.loads(private.read_text())['levels'] if private.exists() else approved
    # Crates, minimum pushes, and unavoidable extra pushes caused by sharing
    # the rooms with other crates. These are solution minima, not route padding.
    difficulty = {54: (4, 27, 8), 55: (4, 33, 8), 56: (5, 39, 14), 57: (5, 47, 12)}
    for number, (crate_count, minimum, detours) in difficulty.items():
        level = classic[number - 1]
        assert level == approved[number - 1], f'Classic {number}: campaign copies differ'
        board, tiles = cells(level['cells']), cells(level['tiles'])
        # Keep the proof applicable: no portals, powers, alternate objectives,
        # blocking scenery or special floors that would bypass Sokoban rules.
        assert set(board) <= {0, 7, 9, 10, 18}
        assert set(tiles) <= WALLS | {0, 77, 99, 100, 101, 102, 103}
        assert set(cells(level['decorations'])) <= {0, 57, 58, 59, 135, 136, 137}
        assert board.count(9) == board.count(18) == crate_count
        assert board.count(10) == board.count(7) == 1
        data = ''.join(''.join(level[key]) for key in ('cells', 'tiles', 'decorations'))
        solved = subprocess.run([str(SOLVER), 'solve', '--level', str(number),
                                 '--only', 'macro-bfs', '--seconds', '90',
                                 '--max-states', '2500000', '--max-mb', '192', data],
                                capture_output=True, text=True, timeout=100)
        assert solved.returncode == 0, f'Classic {number}: {solved.stderr}'
        replay = subprocess.run([str(SOLVER), 'explain', '--level', str(number),
                                 data, solved.stdout.strip()], capture_output=True,
                                text=True, timeout=10)
        assert replay.returncode == 0, f'Classic {number}: {replay.stderr}'
        proof = json.loads(replay.stdout)
        assert proof['pushes'] == proof['crate_pushes'] == minimum, (number, proof)
        assert proof['goals'] == crate_count and not proof['events_truncated']
        independent = independent_pushes(board, tiles)
        assert minimum - independent >= detours, (number, minimum, independent)
        pushes = [event for event in proof['events'] if event['piece'] == 9]
        assert len({event['piece_id'] for event in pushes}) == crate_count
        switches = sum(a['piece_id'] != b['piece_id'] for a, b in zip(pushes, pushes[1:]))
        assert switches >= crate_count, f'Classic {number}: crates must be interleaved'
        print(f'Classic {number}: fresh engine solution, {proof["moves"]} moves, '
              f'{minimum} minimum pushes, {minimum - independent} required detour pushes',
              flush=True)


if __name__ == '__main__':
    main()
