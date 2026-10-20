#!/usr/bin/env python3
"""Every picture the game draws and every sound it plays exists, has the
expected size or format, and is listed in its folder's art.json or
sounds.json with a matching checksum."""
import hashlib
import json
from pathlib import Path
import re
import wave

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

classic = [f'tile-{kind}' for kind in range(41)]
classic += [f'{kind}-{facing}' for kind in ('player', 'charged') for facing in ('left', 'up', 'right', 'down')]
classic += ['shadow', 'door-open', 'projectile'] + [f'sensor-{frame}' for frame in range(1, 9)]
expected = [f'assets/shovey/sprites/{name}.png' for name in classic]
expected += [f'assets/shovey-landscape/sprites/{name}.png' for name in classic]
expected += [f'assets/shovey-island/tiles/{kind}.png' for kind in range(125) if kind not in (50, 79)]
expected += [f'assets/shovey-island-landscape/tiles/{kind}.png' for kind in range(125) if kind not in (50, 79)]
expected += [f'assets/shovey-island/player/{facing}.png' for facing in range(1, 5)]
expected += [f'assets/shovey-island-landscape/player/{facing}.png' for facing in range(1, 5)]
for path in expected:
    with Image.open(ROOT / path) as image:
        assert image.size == (128, 128) and image.mode == 'RGBA', path
for path in ('assets/shovey/preview.png', 'assets/shovey-island/preview.png', 'assets/shovey-editor/preview.png'):
    with Image.open(ROOT / path) as image:
        assert image.size == (480, 288), path
for path in (ROOT / 'assets/shovey/levels').glob('*.png'):
    with Image.open(path) as image:
        assert image.size == (192, 320), path
for path in (ROOT / 'assets/shovey-island/levels').glob('*.png'):
    with Image.open(path) as image:
        assert image.size == (192, 320), path

listed = set()
for folder in ('assets/shovey', 'assets/shovey-landscape', 'assets/shovey-island',
               'assets/shovey-island-landscape', 'assets/shovey-editor'):
    art = json.loads((ROOT / folder / 'art.json').read_text())
    for item in art['files']:
        data = (ROOT / folder / item['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
        assert item['depicts'], item['path']
        listed.add(f'{folder}/{item["path"]}')
missing = set(expected) - listed
assert not missing, f'Not described in art.json: {sorted(missing)[:5]}'

# Every sound a view plays is a short mono 16-bit 22050 Hz WAV in its
# edition's folder, described in that folder's sounds.json.
views = (ROOT / 'apps/shovey/shovey_view.zi').read_text() + (ROOT / 'apps/shovey/island/island_view.zi').read_text()
played = sorted(set(re.findall(r'assets/shovey(?:-island)?/sounds/[a-z]+\.wav', views)))
assert played, 'No sounds played'
for path in played:
    folder, name = path.split('/sounds/')
    described = {item['file']: item for item in json.loads((ROOT / folder / 'sounds.json').read_text())['files']}
    item = described[f'sounds/{name}']
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == item['sha256'], path
    assert item['what'] and item['prompt'] and item['model'], path
    with wave.open(str(ROOT / path)) as sound:
        assert (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) == (1, 2, 22050), path
        assert 0.1 <= sound.getnframes() / 22050 <= 1.5, path
print(f'Assets: {len(expected)} sprites, three cards and {len(played)} sounds present, sized and described')
