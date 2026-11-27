"""Limit shipped Classic previews to the approved campaign; keep source intact."""
import json
import hashlib
from pathlib import Path
from wall_tiles import WALL_KINDS, wall_name, pit_floor


def pack_sprite_atlases(resources):
    """Keep the shared runtime atlas; preserve loose PNGs in the source tree."""
    for atlas in resources.rglob('atlas.png'):
        if atlas.parent.name not in ('sprites', 'sprites-landscape'):
            continue
        landscape = atlas.parent.name == 'sprites-landscape' or atlas.parent.parent.name == 'landscape'
        for sprite in atlas.parent.glob('*.png'):
            if sprite != atlas or landscape:
                sprite.unlink()
    for manifest in resources.rglob('art.json'):
        art = json.loads(manifest.read_text())
        art['files'] = [item for item in art['files'] if (manifest.parent / item['path']).is_file()]
        manifest.write_text(json.dumps(art, indent=2) + '\n')


def prepare_release_assets(source, resources):
    levels = json.loads((source / 'levels/approved.json').read_text())['levels']
    approved = len(levels)
    for path in resources.rglob('*.png'):
        if path.parent.name not in ('levels', 'levels-landscape') or not path.stem.isdecimal():
            continue
        if int(path.stem) > approved:
            path.unlink()
    # Approved snapshots may differ from the board currently being edited.
    # Compose their previews from those same snapshots, not authoring files.
    from PIL import Image
    for target, landscape in ((resources / 'levels', False), (resources / 'levels-landscape', True),
                              (resources / 'landscape/levels', True), (resources / 'classic/levels', False)):
        if not target.is_dir():
            continue
        folder = source / ('assets/shovey-landscape/sprites' if landscape else 'assets/shovey/sprites')
        sprites = {}
        def sprite(name):
            if name not in sprites:
                sprites[name] = Image.open(folder / (name + '.png')).convert('RGBA').resize((16, 16), Image.Resampling.NEAREST)
            return sprites[name]
        for level in levels:
            level = dict(level, **level.get('engine_variant', {}))
            layers = [''.join(level.get(name, ['00' * 12] * 20)) for name in ('cells', 'tiles', 'decorations')]
            board = [[int(layer[i:i + 2], 16) for i in range(0, 480, 2)] for layer in layers]
            walls = [kind if kind in WALL_KINDS else board[1][at] for at, kind in enumerate(board[0])]
            for at, kind in enumerate(board[0]):
                if kind in {105, 117, 119, 121}:
                    walls[at] = 0
            picture = Image.new('RGBA', (320, 192) if landscape else (192, 320))
            for at in range(240):
                display = (11 - at % 12) * 20 + at // 12 if landscape else at
                position = (display % (20 if landscape else 12) * 16, display // (20 if landscape else 12) * 16)
                tile = board[1][at]
                if board[0][at] in {105, 117, 119, 121} and tile in WALL_KINDS:
                    tile = {95: 99, 96: 100, 97: 101, 98: 102, 127: 99, 128: 100, 129: 101, 130: 102, 164: 163}.get(tile, 0)
                if tile in {4, 5, 6, 47, 48, 49}:
                    picture.alpha_composite(sprite(f'tile-{pit_floor(at, board[1])}'), position)
                picture.alpha_composite(sprite(wall_name(tile, at, walls, landscape)), position)
                for kind in (board[2][at], board[0][at]):
                    if kind:
                        picture.alpha_composite(sprite('player-up' if kind == 10 else wall_name(kind, at, walls, landscape)), position)
            picture.convert('RGB').quantize(colors=192, method=2, dither=1).save(target / f'{level["number"]}.png', optimize=True)
    manifest = resources / 'art.json'
    if manifest.exists():
        value = json.loads(manifest.read_text())
        value['files'] = [item for item in value['files'] if (resources / item['path']).is_file()]
        for item in value['files']:
            item['sha256'] = hashlib.sha256((resources / item['path']).read_bytes()).hexdigest()
        manifest.write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    import sys
    prepare_release_assets(Path(__file__).resolve().parents[1], Path(sys.argv[1]))
