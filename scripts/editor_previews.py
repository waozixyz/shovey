#!/usr/bin/env python3
"""The map of every place for the private editor's level overview.

    python3 scripts/editor_previews.py

The editor writes backup/editor-drafts/previews/wanted.txt, one line per
place: its number and its board as hexadecimal text. Each board is drawn in
landscape as previews/NNN-HASH.png, where HASH is the board's 32-bit FNV-1a
in hexadecimal; pictures that exist are kept and older ones of the same
place removed. The boards are then joined edge to edge, 15 to a row, into
previews/map-HASH.png, where HASH is the FNV-1a of all the boards' hashes in
order, so a changed board never shows an old map.
"""
import fcntl
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/levels'))
import levels  # noqa: E402

FOLDER = ROOT / 'backup/editor-drafts/previews'
CELL = 8
COLUMNS = 15


def fnv(text):
    value = 2166136261
    for byte in text.encode():
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return f'{value:08x}'


def picture(board, sprites):
    from PIL import Image
    kinds = [int(board[at:at + 2], 16) for at in range(0, len(board), 2)]
    pieces, floors, decorations = kinds[:levels.CELLS], kinds[levels.CELLS:2 * levels.CELLS], kinds[2 * levels.CELLS:]
    image = Image.new('RGBA', (levels.HEIGHT * CELL, levels.WIDTH * CELL))

    def put(name, at):
        display = (levels.WIDTH - 1 - at % levels.WIDTH) * levels.HEIGHT + at // levels.WIDTH
        try:
            image.alpha_composite(sprites.get(name), (display % levels.HEIGHT * CELL, display // levels.HEIGHT * CELL))
        except FileNotFoundError:
            pass

    # The same layers as the game's level pictures.
    for at, kind in enumerate(pieces):
        tile = floors[at]
        if kind in {105, 117, 119, 121} and tile in levels.CLASSIC_WALL_FLOORS:
            tile = levels.CLASSIC_WALL_FLOORS[tile]
        put(f'tile-{tile}', at)
        if decorations[at]:
            put(f'tile-{decorations[at]}', at)
        if kind == levels.CLASSIC_PLAYER:
            put('player-up', at)
        elif kind != 0:
            put(f'tile-{kind}', at)
    return image


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    with (FOLDER / 'render.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # Another run is drawing them.
        wanted = {}
        for line in (FOLDER / 'wanted.txt').read_text().split('\n'):
            number, _, board = line.partition(' ')
            if number.isdigit() and len(board) == 6 * levels.CELLS:
                wanted[int(number)] = board
        from PIL import Image
        sprites = levels.Sprites(ROOT / 'assets/shovey-landscape/sprites', CELL)
        drawn = 0
        names = []
        for number, board in sorted(wanted.items()):
            name = f'{number:03}-{fnv(board)}.png'
            names.append(name)
            for old in FOLDER.glob(f'{number:03}-*.png'):
                if old.name != name:
                    old.unlink(missing_ok=True)
            if not (FOLDER / name).exists():
                levels.save(picture(board, sprites), FOLDER / name)
                drawn += 1
        width, height = levels.HEIGHT * CELL, levels.WIDTH * CELL
        rows = (len(names) + COLUMNS - 1) // COLUMNS
        whole = Image.new('RGB', (COLUMNS * width, rows * height), (24, 28, 27))
        for index, name in enumerate(names):
            with Image.open(FOLDER / name) as tile:
                whole.paste(tile.convert('RGB'), (index % COLUMNS * width, index // COLUMNS * height))
        map_name = f"map-{fnv(''.join(name[4:12] for name in names))}.png"
        for old in FOLDER.glob('map-*.png'):
            if old.name != map_name:
                old.unlink(missing_ok=True)
        levels.save(whole, FOLDER / map_name)
        print(f'drew {drawn} of {len(wanted)} place pictures and {map_name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
