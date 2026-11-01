#!/usr/bin/env python3
"""Level125 requires all three crate-family pieces without extra wall filler.

The live base remains playable by the old engine. Only new builds consume its
engine_variant and exact retired-board guard. Both stored and fresh solver
routes are replayed through the shipped game engine.
"""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/solver'))
from barrels_analysis import board, proof

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'


def cells(rows):
    data = ''.join(rows)
    return [int(data[i:i + 2], 16) for i in range(0, len(data), 2)]


def main():
    campaign = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    for base_level in campaign:
        assert all(kind <= 134 or 143 <= kind <= 156 for kind in cells(base_level['cells'])), 'Live base uses an unsupported old-engine piece'
        assert proof(base_level['number'], board(base_level, True), base_level['solution']), ('Old-rule live base fails', base_level['number'])
    base = campaign[124]
    level = dict(base, **base['engine_variant'])
    assert level['tiles'] == base['tiles'] and level['decorations'] == base['decorations'], 'No wall or scenery filler'
    old_cells, new_cells = cells(base['cells']), cells(level['cells'])
    changed = [(i, a, b) for i, (a, b) in enumerate(zip(old_cells, new_cells)) if a != b]
    assert changed == [(161, 0, 18), (208, 0, 18)], changed
    assert new_cells.count(18) == 3 and new_cells.count(9) == 1
    assert cells(level['decorations']).count(141) == 2
    # Under the old rules a barrel has the same behavior as a stump.
    assert proof(125, board(base, True), base['solution']), 'Old installs retain a winning route'
    stored = proof(125, board(level), level['solution'])
    assert stored and stored['goals'] == 7
    assert len({event['piece_id'] for event in stored['events'] if event['piece'] == 141}) == 2
    assert any(event['piece'] == 9 for event in stored['events'])
    result = subprocess.run([str(SOLVER), 'solve', '--level', '125', '--only', 'greedy',
                             '--seconds', '10', '--max-states', '350000', '--max-mb', '96', board(level)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    fresh = proof(125, board(level), result.stdout.strip())
    assert fresh and fresh['goals'] == 7
    assert len({event['piece_id'] for event in fresh['events'] if event['piece'] == 141}) == 2
    assert any(event['piece'] == 9 for event in fresh['events'])
    private = ROOT / 'levels/classic.json'
    if private.exists():
        assert json.loads(private.read_text())['levels'][124] == base
    print(f"Classic125: stored/fresh engine replay, {fresh['moves']} moves/{fresh['pushes']} pushes; "
          f'crate and both barrels required, no added walls; all {len(campaign)} live bases replay under old barrel rules')


if __name__ == '__main__':
    main()
