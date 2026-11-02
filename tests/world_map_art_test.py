"""Verify exact frozen delivery and its source adapter without regenerating art."""
import hashlib
import json
from pathlib import Path
import re
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'assets/shovey/world-map'
manifest = json.loads((folder / 'riverfold.json').read_text())
receipt = json.loads((folder / 'asset-receipt.json').read_text())
source = (ROOT / 'src/world_map_art.zi').read_text()
assert (manifest['worldWidth'], manifest['worldHeight'], manifest['baseWidth']) == (5079, 53360, 1200)
assert len(manifest['panels']) == 38 and len(manifest['nodes']) == 175 and len(manifest['edges']) == 180
assert len(receipt['assets']) == 24 and receipt['totalBytes'] == 14476988
assert {p.name for p in folder.glob('*.webp')} == {Path(a['path']).name for a in receipt['assets']}
registered = {entry['path']: entry['sha256'] for entry in json.loads((ROOT / 'assets/shovey/art.json').read_text())['files']}
for asset in receipt['assets']:
    path = ROOT / asset['path']
    digest = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
    assert digest == asset['sha256'] == registered[str(path.relative_to(ROOT / 'assets/shovey'))]
    assert path.stat().st_size == asset['bytes']
    with Image.open(path) as image:
        assert image.size == (asset['nativeWidth'], asset['nativeHeight'])
axes = {}
for axis in ('x', 'y'):
    match = re.search(r'world_map_art_' + axis + r': \[175\]float32 = \.\[([^;]+)\];', source)
    assert match
    axes[axis] = list(map(float, match[1].split(',')))
for index, node in enumerate(manifest['nodes']):
    assert max(abs(axes[axis][index] - node[axis]) for axis in axes) < .000001
for edge in manifest['edges']:
    name = f'world_map_art_route_{edge["from"]}_{edge["to"]}'
    match = re.search(name + r': \[\d+\]Vector2 = \.\[([^;]+)\];', source)
    assert match
    points = [[float(value.split('=')[-1]) for value in point.split(',')] for point in re.findall(r'Vector2\.\{([^}]+)\}', match[1])]
    assert len(points) == len(edge['points'])
    assert all(max(abs(x - y) for x, y in zip(a, b)) < .000001 for a, b in zip(points, edge['points']))
    assert f'return {name}[:]' in source
    assert 1 <= edge['from'] < edge['to'] <= 175
print('Riverfold delivery local test passed: exact24WebPs/14,476,988bytes,38instances,175positions,180intermediate routes; no obsolete binaries')
