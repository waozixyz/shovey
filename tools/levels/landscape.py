"""Prepare upright objects and board-aligned terrain for landscape.

The engines keep one portrait board. Landscape is a presentation of that
same board. Shores, directional markers and player facings turn with the
board; houses, items and other fixed artwork stay upright on the screen.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
COPIES = (
    ('assets/shovey/sprites', 'assets/shovey-landscape/sprites'),
    ('assets/shovey-island/tiles', 'assets/shovey-island-landscape/tiles'),
    ('assets/shovey-island/player', 'assets/shovey-island-landscape/player'),
)


def turns_with_board(path):
    if path.parent.name == 'player':
        return True
    if path.parent.name == 'sprites':
        return path.stem.startswith(('player-', 'charged-')) or path.stem in ('shadow', 'tile-40')
    kind = int(path.stem)
    return (2 <= kind <= 9 or 11 <= kind <= 12 or 14 <= kind <= 23
            or 85 <= kind <= 88 or 117 <= kind <= 120)


def landscape_bytes(path):
    if not turns_with_board(path):
        return path.read_bytes()
    with Image.open(path) as image:
        turned = image.transpose(Image.Transpose.ROTATE_90).convert('RGBA')
    output = io.BytesIO()
    turned.save(output, format='PNG', optimize=True)
    return output.getvalue()


def manifest_entry(source_manifest, source_path, target_root, target_path):
    source_relative = source_path.relative_to(source_manifest.parent).as_posix()
    depicts = next(item['depicts'] for item in json.loads(source_manifest.read_text())['files']
                   if item['path'] == source_relative)
    return {
        'path': target_path.relative_to(target_root).as_posix(),
        'depicts': f'landscape presentation of {depicts}',
        'sha256': hashlib.sha256(target_path.read_bytes()).hexdigest(),
    }


def run(check):
    changed = []
    manifests = {}
    for source_name, target_name in COPIES:
        source_folder = ROOT / source_name
        target_folder = ROOT / target_name
        source_manifest = source_folder.parent / 'art.json'
        target_root = target_folder.parent
        manifest_path = target_root / 'art.json'
        manifest = manifests.setdefault(manifest_path, {
            'generator': 'tools/levels/landscape.py',
            'method': 'Objects stay upright; player facings, directional markers and shore edges turn counterclockwise with the board. No outside image is used.',
            'files': [],
        })
        expected = {}
        for source in sorted(source_folder.glob('*.png')):
            target = target_folder / source.name
            data = landscape_bytes(source)
            expected[target] = data
            if check:
                if not target.is_file() or target.read_bytes() != data:
                    changed.append(target.relative_to(ROOT).as_posix())
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        manifest['files'] = [item for item in manifest['files'] if target_root / item['path'] not in expected]
        for target in sorted(expected):
            source = Path(str(target).replace('-landscape/', '/'))
            manifest['files'].append(manifest_entry(source_manifest, source, target_root, target))
    for manifest_path, manifest in manifests.items():
        manifest['files'].sort(key=lambda item: item['path'])
        wanted = json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'
        if check:
            if not manifest_path.is_file() or manifest_path.read_text() != wanted:
                changed.append(manifest_path.relative_to(ROOT).as_posix())
        else:
            manifest_path.write_text(wanted)
    if changed:
        print('out of date: ' + ', '.join(changed[:5]))
        return 1 if check else 2
    print(f"Landscape assets: {'checked' if check else 'prepared'} for both editions")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true')
    arguments = parser.parse_args()
    return run(arguments.check)


if __name__ == '__main__':
    raise SystemExit(main())
