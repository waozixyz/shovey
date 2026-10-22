#!/usr/bin/env python3
"""Every board is well formed, has a picture, and its stored solution wins
through the real game engine (the solver's verify mode runs the shipped
Ziran rules). Build the solver first: make solver."""
from concurrent.futures import ThreadPoolExecutor
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


classic = json.loads((ROOT / 'levels/classic.json').read_text())['levels']
island = json.loads((ROOT / 'levels/island.json').read_text())['levels']
assert [level['number'] for level in classic] == list(range(1, len(classic) + 1))
assert [level['number'] for level in island] == list(range(1, len(island) + 1))

checks = []
for level in classic:
    board = cells(level['cells'])
    tiles = cells(level['tiles']) if 'tiles' in level else [0] * CELLS
    decorations = cells(level['decorations']) if 'decorations' in level else [0] * CELLS
    assert all(kind in {0, *range(57, 72), 12, 14, 4, 5, 6, 47, 48, 49, 76, 77, 78, *range(95, 104)} for kind in tiles)
    assert all(kind in {0, 57, 58, 59, 84, 106, 122} for kind in decorations)
    assert board.count(10) == 1, f'Classic {level["number"]}: one Shovey'
    assert board.count(7) >= 1, f'Classic {level["number"]}: a home'
    assert all((kind <= 76 or kind in range(82, 123)) and kind not in (22, 24, 32) for kind in board), f'Classic {level["number"]}: unknown kind'
    assert all(board[at] in (12, 63, 64, 65, 76, 95, 96, 97, 98) or (board[at] in (0, 71) and tiles[at] in (12, 63, 64, 65, 76, 95, 96, 97, 98)) for at in range(CELLS) if at < WIDTH or at >= CELLS - WIDTH or at % WIDTH in (0, WIDTH - 1)), \
        f'Classic {level["number"]}: border needs a solid tile or abyss'
    assert (ROOT / f'assets/shovey/levels/{level["number"]}.png').is_file()
    assert (ROOT / f'assets/shovey/levels-landscape/{level["number"]}.png').is_file()
    # The last Classic level is the finale picture, with nothing to solve.
    if level['number'] < len(classic):
        assert set(level['solution']) <= set('0123ft') and level['solution'], f'Classic {level["number"]}: solution'
        checks.append(('classic', level['number'], ''.join(level['cells']) + ''.join(level.get('tiles', [])) + ''.join(level.get('decorations', [])), level['solution']))

names = [level['name'] for level in island]
assert all(names) and len(set(names)) == len(island), 'Every island has its own name'
for level in island:
    terrain, objects = cells(level['terrain']), cells(level['objects'])
    assert objects.count(56) == 1, f'Island {level["number"]}: one Shovey'
    assert objects.count(75) >= 1, f'Island {level["number"]}: a hut'
    assert all(kind <= 48 for kind in terrain) and all(kind <= 124 and kind not in (50, 79) for kind in objects)
    assert (ROOT / f'assets/shovey-island/levels/{level["number"]}.png').is_file()
    assert (ROOT / f'assets/shovey-island/levels-landscape/{level["number"]}.png').is_file()
    assert set(level['solution']) <= set('0123') and level['solution'], f'Island {level["number"]}: solution'
    checks.append(('island', level['number'], ''.join(level['terrain']) + ''.join(level['objects']), level['solution']))

with ThreadPoolExecutor(8) as pool:
    results = list(pool.map(lambda check: (check[0],) + verify(*check), checks))
failed = [f'{edition} {level}' for edition, level, ok in results if not ok]
assert not failed, 'Stored solutions that do not win: ' + ', '.join(failed)
print(f'Levels: {len(classic)} Classic and {len(island)} Island boards, pictures, and {len(checks)} solutions won through the engine')
