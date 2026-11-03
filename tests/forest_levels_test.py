#!/usr/bin/env python3
"""Solve and replay the forest crossing and brick-building levels through the shipped rules.

The optional engine variant keeps the live campaign playable by older engines:
only a new build sees the bee board, and exact retired-board matching installs
it without touching a custom board. The live document's base boards and routes
remain independently playable by engines without the new piece kinds.
"""
import json
from pathlib import Path
import re
import subprocess

from classic_63_65_68_test import data, explain, rows
from classic_difficulty_test import cells, neighbor

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'


def solve(level, method='macro-bfs', impossible=False):
    result = subprocess.run([str(SOLVER), 'solve', '--level', str(level['number']),
                             '--only', method, '--seconds', '20', '--max-states',
                             '500000', '--max-mb', '96', data(level)],
                            capture_output=True, text=True, timeout=30)
    if impossible:
        assert result.returncode == 1 and '"stop":"exhausted"' in result.stderr, result.stderr
        return None
    assert result.returncode == 0, (level['number'], result.stderr)
    return explain(level, result.stdout.strip())


def enclosed(level, wall):
    """A complete outline and one connected floor, including portal links."""
    board, terrain = (cells(level[k]) for k in ('cells', 'tiles'))
    assert board.count(10) == board.count(7) == 1
    border = {at for at in range(240) if at % 12 in (0, 11) or at // 12 in (0, 19)}
    assert all(terrain[at] == wall and board[at] == 0 for at in border), 'Missing enclosing wall'
    floor = {at for at in range(240) if terrain[at] != wall}
    assert all(at in floor for at, kind in enumerate(board) if kind), 'Object embedded in a wall'
    portals = {at for at, kind in enumerate(board) if kind == 8}
    reached = {board.index(10)}
    pending = list(reached)
    for at in pending:
        adjacent = {neighbor(at, side) for side in range(4)}
        if at in portals:
            adjacent |= portals
        for to in adjacent & floor - reached:
            reached.add(to)
            pending.append(to)
    assert reached == floor, 'Unintended disconnected floor'


def main():
    approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    retired = (ROOT / 'src/official_updates.zi').read_text()
    old93 = re.search(r'RETIRED_CLASSIC_93 :: "([0-9a-f]+)"', retired)[1]
    assert data(approved[92]) == old93, 'Older players retain the exact playable base 93'
    assert 'engine_variant' in approved[92]
    assert all(0 <= kind <= 134 or 143 <= kind <= 156
               for level in approved for kind in cells(level['cells'])), \
        'New piece kinds must not make older players reject the live campaign'
    explain(approved[92], approved[92]['solution'])
    private = ROOT / 'levels/classic.json'
    classic = json.loads(private.read_text())['levels'] if private.exists() else approved
    for number in (93, 94, 97, 98, 99):
        source = approved[number - 1]
        assert source == classic[number - 1], (number, 'campaign copies differ')
        level = dict(source, **source.get('engine_variant', {}))
        board, terrain, decorations = (cells(level[k]) for k in ('cells', 'tiles', 'decorations'))
        stored = explain(level, level['solution'])
        found = stored if number == 94 else solve(level, 'macro-bfs' if number in (93, 97) else 'greedy')
        assert stored['goals'] == found['goals']
        if number in (97, 98, 99):
            # Three complete buildings, without the old disconnected yard
            # strips or an exit through the edge of the board.
            enclosed(level, 96)
            assert set(terrain) <= {77, 60, 96, 100, 102}
            assert set(decorations) <= {0, 106, 139, 140}
            assert not set(board) & {64, 70, 150, 151, 152, 153, 154, 155, 156, 167, 168}
            assert all(terrain[at] == 96 for at, kind in enumerate(decorations) if kind), 'Props occupy wall niches'
            assert board.count(9) == board.count(18)
        if number == 93:
            assert set(terrain) <= {162, 64}
            assert board.count(167) == board.count(168) == 1
            assert sum(e['piece'] == 168 for e in stored['events']) >= 3
            assert board.count(71) == 2 and stored['crate_pushes'] >= 2
            no_hive = [0 if kind == 168 else kind for kind in board]
            solve(dict(level, cells=rows(no_hive)), impossible=True)
        elif number == 94:
            enclosed(level, 98)
            assert not set(board) & {89, 90, 91}, 'The garden contains balls, not fish'
            assert stored['goals'] == 13 and stored['used_features'] & 78 == 78
            assert board.count(9) == 3 and board.count(18) == 2 and board.count(13) == 1
        elif number == 97:
            assert board.count(9) == board.count(18) == stored['goals'] == 3
            assert stored['crate_pushes'] == found['crate_pushes'] == 28
            assert len({e['piece_id'] for e in stored['events'] if e['piece'] == 9}) == 3
        elif number == 98:
            assert board.count(19) == 3 and board.count(9) == board.count(18) == 1
            assert stored['goals'] == 4 and stored['pushes'] >= 20
            # An odd trio must disappear together. Merging only two strands
            # the remaining star; the actual replay drops all three at once.
            remaining = stored['goals']
            merges = []
            for event in stored['events']:
                if event['piece'] == 19 and event['remaining'] < remaining:
                    merges.append(remaining - event['remaining'])
                remaining = event['remaining']
            assert merges == [3]
            assert len({e['piece_id'] for e in stored['events'] if e['piece'] == 19}) == 3
        else:
            assert board.count(2) == 2 and board.count(9) == board.count(18) == 1
            assert stored['used_features'] & 32 and not stored['used_features'] & 128
            paint = [e for e in stored['events'] if e['features'] & 32]
            assert [e['target'] for e in paint] == [17, 15]
            assert paint[0]['piece_id'] != paint[1]['piece_id']
            first_finish = next(e for e in stored['events'] if e['target'] == 6)
            assert first_finish['piece_id'] == paint[0]['piece_id'] and first_finish['step'] > paint[1]['step']
            assert any(e['piece_id'] == paint[0]['piece_id'] and e['destination'] == [8, 5]
                       and paint[0]['step'] < e['step'] < paint[1]['step'] for e in stored['events']), 'Green ball waits in the side bay'
            assert stored['goals'] == 3
        proof = 'stored engine replay wins' if number == 94 else 'fresh solver and stored replay win'
        print(f'Classic {number}: {proof}; {stored["moves"]} moves, '
              f'{stored["pushes"]} pushes, stage materials preserved', flush=True)
    print('Compatibility: original 93 remains live-readable; new builds ship its bee variant')


if __name__ == '__main__':
    main()
