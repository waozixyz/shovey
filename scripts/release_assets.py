"""Limit shipped Classic previews to the approved campaign; keep source intact."""
import json
import hashlib
from pathlib import Path


def prepare_release_assets(source, resources):
    levels = json.loads((source / 'levels/approved.json').read_text())['levels']
    approved = len(levels)
    for path in resources.rglob('*.png'):
        if path.parent.name not in ('levels', 'levels-landscape') or not path.stem.isdecimal():
            continue
        if 'island' in path.parts or int(path.stem) > approved:
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
            layers = [''.join(level.get(name, ['00' * 12] * 20)) for name in ('cells', 'tiles', 'decorations')]
            board = [[int(layer[i:i + 2], 16) for i in range(0, 480, 2)] for layer in layers]
            picture = Image.new('RGBA', (320, 192) if landscape else (192, 320))
            for at in range(240):
                display = (11 - at % 12) * 20 + at // 12 if landscape else at
                position = (display % (20 if landscape else 12) * 16, display // (20 if landscape else 12) * 16)
                picture.alpha_composite(sprite(f'tile-{board[1][at]}'), position)
                for kind in (board[2][at], board[0][at]):
                    if kind:
                        picture.alpha_composite(sprite('player-up' if kind == 10 else f'tile-{kind}'), position)
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
