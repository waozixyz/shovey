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
from classic_difficulty_test import cells

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
    for number in (93, 97, 98, 99):
        source = approved[number - 1]
        assert source == classic[number - 1], (number, 'campaign copies differ')
        level = dict(source, **source.get('engine_variant', {}))
        board, terrain, decorations = (cells(level[k]) for k in ('cells', 'tiles', 'decorations'))
        stored = explain(level, level['solution'])
        found = solve(level, 'macro-bfs' if number == 93 else 'greedy')
        assert stored['goals'] == found['goals']
        if number != 93:
            # Buildings use brick floors, wall outlines, paved courtyards,
            # lamps and pots. Levels 98/99 also retain their surrounding wall.
            assert set(terrain) <= {77, 60, 96, 100}
            perimeter = set()
            if number in (98, 99):
                perimeter = {at for at in range(240)
                             if at // 12 < 3 or at // 12 == 19 or at % 12 in (0, 11)}
                doorway = 19 * 12 + 6
                assert terrain[doorway] == 100, 'Keep the building entrance open'
                perimeter.remove(doorway)
                assert all(terrain[at] == 96 for at in perimeter), 'Missing surrounding brick wall'
            assert 80 <= terrain.count(100) <= 120
            assert sum(kind == 96 for at, kind in enumerate(terrain) if at not in perimeter) <= 56
            assert set(decorations) <= {0, 106, 139, 140}
            assert not set(board) & {64, 70, 150, 151, 152, 153, 154, 155, 156, 167, 168}
            for at, kind in enumerate(terrain):
                if kind != 96 or at in perimeter: continue
                x, y = at % 12, at // 12
                assert any(terrain[(y + dy) * 12 + x + dx] == 100
                           for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                           if 0 <= x + dx < 12 and 0 <= y + dy < 20), 'No wall filler'
        if number == 93:
            assert set(terrain) <= {162, 64}
            assert board.count(167) == board.count(168) == 1
            assert sum(e['piece'] == 168 for e in stored['events']) >= 3
            assert board.count(71) == 2 and stored['crate_pushes'] >= 2
            no_hive = [0 if kind == 168 else kind for kind in board]
            solve(dict(level, cells=rows(no_hive)), impossible=True)
        elif number == 97:
            assert board.count(9) == 3 and board.count(18) == 2
            assert board.count(132) == board.count(128) == 1
            assert stored['crate_pushes'] >= 11 and stored['goals'] == 3
            assert any(e['piece'] == 9 and e['target'] == 132 for e in stored['events'])
        elif number == 98:
            assert board.count(19) == 2 and board.count(9) == board.count(18) == 1
            assert stored['crate_pushes'] >= 16 and stored['pushes'] >= 28 and stored['goals'] == 4
        else:
            assert board.count(2) == 2 and board.count(9) == board.count(18) == 1
            assert stored['used_features'] & 32 and not stored['used_features'] & 128
            assert {15, 17} <= {e['target'] for e in stored['events'] if e['piece'] in (2, 3)}
            assert stored['goals'] == 4
        print(f'Classic {number}: fresh solver and stored replay win; {stored["moves"]} moves, '
              f'{stored["pushes"]} pushes, stage materials preserved', flush=True)
    print('Compatibility: original 93 remains live-readable; new builds ship its bee variant')


if __name__ == '__main__':
    main()
