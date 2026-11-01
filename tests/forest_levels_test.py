#!/usr/bin/env python3
"""Solve and replay the redesigned forest levels through the shipped rules.

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
    for number in (93, 97, 98):
        source = approved[number - 1]
        assert source == classic[number - 1], (number, 'campaign copies differ')
        level = dict(source, **source.get('engine_variant', {}))
        board, terrain, decorations = (cells(level[k]) for k in ('cells', 'tiles', 'decorations'))
        assert not any(kind in (95, 96, 97, 98, 127, 128, 129, 130) for kind in terrain), \
            f'{number}: no masonry filler'
        assert sum(kind in (12, 14, 62, 63, 76, 164) for kind in terrain) <= 8
        stored = explain(level, level['solution'])
        found = solve(level, 'greedy' if number == 98 else 'macro-bfs')
        assert stored['goals'] == found['goals']
        if number == 93:
            assert board.count(167) == board.count(168) == 1
            assert sum(e['piece'] == 168 for e in stored['events']) >= 3
            assert board.count(71) == 2 and stored['crate_pushes'] >= 2
            no_hive = [0 if kind == 168 else kind for kind in board]
            solve(dict(level, cells=rows(no_hive)), impossible=True)
        elif number == 97:
            assert board.count(150) == board.count(151) == 1 and board.count(156) == 2
            assert stored['used_features'] & 256 and stored['crate_pushes'] >= 2
            assert stored['pushes'] - stored['crate_pushes'] >= 7
        else:
            assert board.count(3) == 2 and board.count(19) == 2
            assert stored['used_features'] & 128 and stored['used_features'] & 32
            assert {15, 16} <= {e['target'] for e in stored['events'] if e['piece'] == 3}
            assert stored['ball_pushes'] >= 8 and stored['goals'] == 4
        print(f'Classic {number}: fresh solver and stored replay win; {stored["moves"]} moves, '
              f'{stored["pushes"]} pushes, no masonry filler', flush=True)
    print('Compatibility: original 93 remains live-readable; new builds ship its bee variant')


if __name__ == '__main__':
    main()
