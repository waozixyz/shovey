#!/usr/bin/env python3
"""Every board is well formed, has a picture, and its stored solution wins
through the real game engine (the solver's verify mode runs the shipped
Ziran rules). Build the solver first: make solver."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOLVER = ROOT / 'build/solver'


WIDTH, HEIGHT, CELLS = 12, 20, 240


def cells(rows):
    assert len(rows) == HEIGHT and all(len(row) == WIDTH * 2 for row in rows)
    text = ''.join(rows)
    return [int(text[at:at + 2], 16) for at in range(0, CELLS * 2, 2)]


def verify(edition, level, board, route):
    result = subprocess.run([str(SOLVER / f'shovey-solve-{edition}'), 'verify', '--level', str(level), board, route],
                            capture_output=True, text=True)
    return level, result.returncode == 0


spec = importlib.util.spec_from_file_location('levels_tool', ROOT / 'tools/levels/levels.py')
levels_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(levels_tool)
classic = levels_tool.load('classic')
published = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
assert [level['number'] for level in classic] == list(range(1, len(classic) + 1))

checks = []
hidden = json.loads((ROOT / 'levels/approved.json').read_text()).get('hidden_levels', [])
assert [level['name'] for level in hidden] == ['29a']
for level in hidden:
    assert all(len(cells(level[key])) == CELLS for key in ('cells', 'tiles', 'decorations'))
    assert level['solution'] and set(level['solution']) <= set('0123ft')
    checks.append(('classic', 1003, ''.join(level['cells'] + level['tiles'] + level['decorations']), level['solution']))
for level in classic:
    board = cells(level['cells'])
    tiles = cells(level['tiles']) if 'tiles' in level else [0] * CELLS
    decorations = cells(level['decorations']) if 'decorations' in level else [0] * CELLS
    assert all(kind in {0, *range(57, 72), 12, 14, 4, 5, 6, 47, 48, 49, 76, 77, 78, *range(95, 104), *range(127,131), 162, 163, 164} for kind in tiles)
    assert all(kind in {0, 57, 58, 59, 84, 106, 122, *range(135, 143), *range(158, 162), 165} for kind in decorations)
    assert board.count(10) == 1, f'Classic {level["number"]}: one Shovey'
    assert board.count(7) + board.count(148) >= 1, f'Classic {level["number"]}: a home or a boat'
    # 143-147 are colour goals, 148 the boat and 149 a floating crate.
    assert all((kind <= 76 or kind in range(82, 135) or kind in range(143, 157)) and kind not in (22, 24, 32) for kind in board), f'Classic {level["number"]}: unknown kind'
    # Open garden borders are valid: the engine bounds movement at the board edge.
    assert (ROOT / f'assets/shovey/levels/{level["number"]}.png').is_file()
    assert (ROOT / f'assets/shovey/levels-landscape/{level["number"]}.png').is_file()
    # Published levels must keep a winning route; unfinished ones may wait.
    if level['number'] <= len(published) or level.get('solution'):
        assert set(level.get('solution', '')) <= set('0123ft') and level.get('solution'), f'Classic {level["number"]}: solution'
        checks.append(('classic', level['number'], ''.join(level['cells']) + ''.join(level.get('tiles', [])) + ''.join(level.get('decorations', [])), level['solution']))

# The secret beaches beside the last level, private like the level files,
# are won by their routes too. They play as an ordinary level number.
secret = ROOT / 'levels/secret.json'
for level in json.loads(secret.read_text())['levels'] if secret.exists() else []:
    assert level['solution'], f'Secret {level["name"]}: solution'
    checks.append(('classic', 1, ''.join(level['cells']) + ''.join(level.get('tiles', [])) + ''.join(level.get('decorations', [])), level['solution']))

with ThreadPoolExecutor(8) as pool:
    results = list(pool.map(lambda check: (check[0],) + verify(*check), checks))
failed = [f'{edition} {level}' for edition, level, ok in results if not ok]
assert not failed, 'Stored solutions that do not win: ' + ', '.join(failed)
print(f'Levels: {len(classic)} Classic boards, pictures, and {len(checks)} solutions won through the engine')
