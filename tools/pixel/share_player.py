#!/usr/bin/env python3
"""Keep Island's player and editor marker identical to Classic's sprites."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def share_player(output_root=ROOT):
    source = ROOT / 'assets/shovey/sprites'
    target = output_root / 'assets/shovey-island'
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / 'art.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'files': []}
    manifest['player_source'] = 'Classic player sprites, copied unchanged by tools/pixel/share_player.py'
    copies = [(f'player/{index}.png', facing)
              for index, facing in enumerate(('up', 'right', 'down', 'left'), 1)]
    copies.append(('tiles/56.png', 'up'))
    for relative, facing in copies:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / f'player-{facing}.png', destination)
        item = next((item for item in manifest['files'] if item['path'] == relative), None)
        if item is None:
            item = {'path': relative}
            manifest['files'].append(item)
        item['depicts'] = f'Shovey looking {facing}, the same player as Classic'
        item['sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print('Island uses Classic\'s exact player sprites in all four directions')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=ROOT)
    share_player(parser.parse_args().output_root)
