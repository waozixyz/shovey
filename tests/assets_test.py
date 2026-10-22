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

classic = [f'tile-{kind}' for kind in (*range(41), *range(44, 79), *range(82, 143))]
classic += ['gate-open', 'gate-open-0', 'gate-open-1', 'gate-open-2'] + [f'abyss-edge-{mask}' for mask in range(16)]
classic += [f'{animal}-{facing}' for animal in ('dog', 'turtle', 'crab') for facing in ('left', 'up', 'right', 'down')]
classic += [f'water-{frame}' for frame in range(4)]
classic += [f'fish-{fish}-{frame}-{facing}' for fish in ('gold', 'koi', 'minnow') for frame in range(4) for facing in ('left', 'up', 'right', 'down')]
classic += [f'grass-edge-{mask}' for mask in range(16)]
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
# Objects and decorations must reveal whichever tile is beneath them.
for kind in (1, 2, 3, 7, 8, 9, 11, 13, 14, 15, 16, 17, 19, 21, 25, 26, 27,
             28, 29, 33, 34, 35, 36, 37, 38, 40, 44, 45, 46, 50, 51, 52, 53, 54, 55,
             56, 57, 58, 59, 62, 71, 66, 67, 68, 69, 72, 73, 74, 75, 82, 83, 84, *range(85, 95), *range(104, 143)):
    with Image.open(ROOT / f'assets/shovey/sprites/tile-{kind}.png') as picture:
        assert picture.getpixel((0, 0))[3] == 0, f'{kind}: object has an attached background'

paint_alpha = Image.open(ROOT / 'assets/shovey/sprites/tile-17.png').getchannel('A').tobytes()
with Image.open(ROOT / 'assets/shovey/sprites/tile-11.png') as trail:
    trail = trail.resize((32, 32), Image.Resampling.NEAREST)
    assert all(trail.getpixel((x, 16))[3] == 255 for x in range(6, 26)), 'Trail bar is not horizontal'
    assert trail.getpixel((16, 11))[3] == 0 and trail.getpixel((16, 22))[3] == 0, 'Trail center should reveal the floor'
for kind in (15, 16, 50, 51, 52):
    assert Image.open(ROOT / f'assets/shovey/sprites/tile-{kind}.png').getchannel('A').tobytes() == paint_alpha, \
        f'{kind}: paint silhouette differs from the other colors'

with Image.open(ROOT / 'assets/shovey/sprites/tile-12.png') as stone:
    pixels = [stone.getpixel((x, y)) for y in range(stone.height) for x in range(stone.width)]
    assert all(b <= r and b <= g for r, g, b, a in pixels if a), 'Stone wall has a blue tint'
    assert len(set(pixels)) > 30, 'Stone wall lost its grain'

# The duck has four actual views. Separate the bright orange bill from its
# brown wing and the feet below it, then check its direction on the screen.
for facing, dx, dy in (('left', -1, 0), ('up', 0, -1), ('right', 1, 0), ('down', 0, 1)):
    with Image.open(ROOT / f'assets/shovey/sprites/dog-{facing}.png') as image:
        picture = image.resize((32, 32), Image.Resampling.NEAREST)
        bounds = picture.getchannel('A').getbbox()
        assert bounds[3] - bounds[1] >= 24, f'Duck {facing} was shrunk by stray transparent pixels'
        points = {(x, y) for y in range(20) for x in range(32)
                  if (lambda c: c[3] > 128 and c[0] > 225 and 80 < c[1] < 190 and c[2] < 70)(picture.getpixel((x, y)))}
    components = []
    while points:
        group = {points.pop()}
        pending = list(group)
        while pending:
            x, y = pending.pop()
            for neighbor in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if neighbor in points:
                    points.remove(neighbor); group.add(neighbor); pending.append(neighbor)
        components.append(group)
    bill = max(components, key=len)
    assert sum((x - 15.5) * dx + (y - 15.5) * dy for x, y in bill) / len(bill) > 0.25, f'Duck faces away from {facing}'

for index, facing in enumerate(('up', 'right', 'down', 'left'), 1):
    classic_player = ROOT / f'assets/shovey/sprites/player-{facing}.png'
    island_player = ROOT / f'assets/shovey-island/player/{index}.png'
    assert classic_player.read_bytes() == island_player.read_bytes(), \
        f'Island must use Classic\'s exact player facing {facing}'
assert (ROOT / 'assets/shovey-island/tiles/56.png').read_bytes() == \
    (ROOT / 'assets/shovey/sprites/player-up.png').read_bytes(), \
    'Island\'s editor marker must use the same player'
for path in ('assets/shovey/preview.png', 'assets/shovey-island/preview.png', 'assets/shovey-editor/preview.png'):
    with Image.open(ROOT / path) as image:
        assert image.size == (480, 288), path
for path in (ROOT / 'assets/shovey/levels').glob('*.png'):
    with Image.open(path) as image:
        assert image.size == (192, 320), path
for path in (ROOT / 'assets/shovey/levels-landscape').glob('*.png'):
    with Image.open(path) as image:
        assert image.size == (320, 192), path
for path in (ROOT / 'assets/shovey-island/levels').glob('*.png'):
    with Image.open(path) as image:
        assert image.size == (192, 320), path
for path in (ROOT / 'assets/shovey-island/levels-landscape').glob('*.png'):
    with Image.open(path) as image:
        assert image.size == (320, 192), path

# Screen rotation changes the board layout, without tipping houses, readable
# numbers or ordinary objects sideways. Directional art still follows the board.
for folder, names in (
        ('shovey/sprites', ('tile-0', 'tile-7', 'tile-21')),
        ('shovey-island/tiles', ('51', '58', '75', '106'))):
    for name in names:
        source = ROOT / 'assets' / folder / (name + '.png')
        target = ROOT / 'assets' / folder.replace('/', '-landscape/', 1) / (name + '.png')
        with Image.open(source) as portrait, Image.open(target) as landscape:
            assert portrait.convert('RGBA').tobytes() == landscape.convert('RGBA').tobytes(), \
                f'{name}: fixed artwork must stay upright'
for folder, names in (
        ('shovey/sprites', tuple(f'{animal}-{facing}' for animal in ('player', 'turtle', 'crab', 'fish-gold-0', 'fish-koi-0', 'fish-minnow-0') for facing in ('up', 'right', 'down', 'left'))),
        ('shovey-island/tiles', ('2', '6', '8', '85', '117'))):
    for name in names:
        source = ROOT / 'assets' / folder / (name + '.png')
        target = ROOT / 'assets' / folder.replace('/', '-landscape/', 1) / (name + '.png')
        with Image.open(source) as portrait, Image.open(target) as landscape:
            expected_turn = portrait.transpose(Image.Transpose.ROTATE_90).convert('RGBA')
            assert expected_turn.tobytes() == landscape.convert('RGBA').tobytes(), \
                f'{name}: directional artwork must follow the board'

# Landscape maps direction to an upright, separately drawn duck view.
facings = ('left', 'up', 'right', 'down')
for index, facing in enumerate(facings):
    portrait = ROOT / f'assets/shovey/sprites/dog-{facings[(index + 3) % 4]}.png'
    landscape = ROOT / f'assets/shovey-landscape/sprites/dog-{facing}.png'
    assert portrait.read_bytes() == landscape.read_bytes(), f'Duck {facing} was rotated instead of redrawn'

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

island_shared = json.loads((ROOT / 'src/island/shared_assets.json').read_text())['copies']
assert {item['from'] for item in island_shared} == {
    'assets/shovey-island-landscape/tiles', 'assets/shovey-island-landscape/player'
}, 'Island must package its rotated sprites with its hosted bundle'

# Every sound a view plays is a short mono 16-bit 22050 Hz WAV in its
# edition's folder, described in that folder's sounds.json.
views = (ROOT / 'src/shovey_view.zi').read_text() + (ROOT / 'src/island/island_view.zi').read_text()
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
