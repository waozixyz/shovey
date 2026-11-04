#!/usr/bin/env python3
"""Check every map edge, paved level center, rail group and source-sized tile."""
import json
import math
from pathlib import Path
import re
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def table(source, name):
    match = re.search(r'\b' + name + r':\s*\[\d+\]\w+\s*=\s*\.\[(.*?)\];', source, re.S)
    assert match, name
    return np.array([float(v) for v in re.sub(r'//[^\n]*', '', match[1]).split(',') if v.strip()])


def main():
    data = json.loads((ROOT / 'assets/shovey/world-map/scenes.json').read_text())
    layout = (ROOT / 'src/world_map_layout.zi').read_text()
    view = (ROOT / 'src/world_map_view.zi').read_text()
    graph = (ROOT / 'src/world_map_progression.zi').read_text()
    edges = table(graph, 'world_map_edges').astype(int).reshape(-1, 2)
    expected = max(math.ceil((source['size'][1 if orientation == 'portrait' else 0] - 128) / data['section_step_native_pixels'])
                   for orientation, source in data['sources'].items())
    failures = []
    if len(data['scenes']) != expected:
        failures.append(f'tile count: {len(data["scenes"])} != source-derived {expected}')
    count = int(re.search(r'WorldMapSceneCount :: (\d+)', layout)[1])
    if count != expected:
        failures.append(f'native scene count: {count} != {expected}')
    for orientation, source in data['sources'].items():
        name = 'world_map_positions' if orientation == 'portrait' else 'world_map_landscape_positions'
        nodes = table(layout, name).reshape(-1, 2)
        assert len(nodes) == 175
        assert np.allclose(nodes, data['nodes'][orientation], atol=.001)
        gaps = np.linalg.norm(nodes[edges[:, 0]-1] - nodes[edges[:, 1]-1], axis=1)
        median = np.median(gaps)
        # The view fits the painting's cross-axis; its framing width cancels
        # WorldMapWorldZoom. A rotated 390-wide phone has 390px map height.
        scale = 390 / source['size'][0 if orientation == 'portrait' else 1]
        print(f'{orientation}: art px min/median/max {gaps.min():.3f}/{median:.3f}/{gaps.max():.3f}; '
              f'390px cross-axis screen {gaps.min()*scale:.3f}/{median*scale:.3f}/{gaps.max()*scale:.3f}')
        for index, gap in enumerate(gaps):
            if not .9 * median <= gap <= 1.1 * median:
                a, b = edges[index]
                failures.append(f'{orientation} {a}->{b}: {gap:.3f} art px outside ±10% of {median:.3f}')
        rails = np.concatenate([table(layout, f'world_map_rail_{orientation}{group}') for group in range(36)]).reshape(-1, 33, 2)
        assert len(rails) == len(edges) == 176
        assert np.allclose(rails[:, 0], nodes[edges[:, 0]-1], atol=.002)
        assert np.allclose(rails[:, -1], nodes[edges[:, 1]-1], atol=.002)
        lengths = np.linalg.norm(np.diff(rails, axis=1), axis=2).sum(axis=1)
        rail_median = np.median(lengths)
        for index, length in enumerate(lengths):
            if not .9 * rail_median <= length <= 1.1 * rail_median:
                failures.append(f'{orientation} rail {tuple(edges[index])}: arc {length:.3f} outside ±10% of {rail_median:.3f}')
        with Image.open(ROOT / source['path']) as image:
            assert list(image.size) == source['size']
            for level, (x, y) in enumerate(nodes, 1):
                x, y = round(x), round(y)
                patch = np.asarray(image.crop((x-3, y-3, x+4, y+4)).convert('RGB')).astype(np.int16)
                r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
                paved = (r>165)&(g>105)&(b>55)&(r-g>4)&(g-b>12)&(r-b>40)
                if paved.mean() < .6:
                    failures.append(f'{orientation} level {level}: off paved pixels ({paved.mean():.2f})')
            if orientation == 'landscape':
                # Sea is cyan/blue, unlike paving, sand, grass or wooden docks.
                offsets = data['secret_offsets_native_pixels']['landscape']
                art = (ROOT / 'src/world_map_art.zi').read_text()
                branch = art.split('    if landscape {', 1)[1].split('    }', 1)[0]
                pairs = re.findall(r'ifx room == 1001 then (-?[\d.]+) else (-?[\d.]+)', branch)
                assert len(pairs) == 2
                assert [float(pair[1]) for pair in pairs] == offsets['1002']
                assert [float(pair[0]) for pair in pairs] == offsets['1001']
                secrets = {room: nodes[28 if room == '1003' else 174] + offset
                           for room, offset in offsets.items()}
                for label, (x, y) in [(f'level {i}', p) for i, p in enumerate(nodes, 1)] + list(secrets.items()):
                    x, y = round(x), round(y)
                    patch = np.asarray(image.crop((x-3, y-3, x+4, y+4)).convert('RGB')).astype(np.int16)
                    r, g, b = np.moveaxis(patch, -1, 0)
                    water = (g > r + 30) & (b > r + 30) & (b > 100)
                    if water.mean() > .2:
                        failures.append(f'landscape {label}: centre in water ({water.mean():.2f})')
                x, y = map(round, secrets['1002'])
                r, g, b = np.moveaxis(np.asarray(image.crop((x-3, y-3, x+4, y+4))).astype(np.int16), -1, 0)
                assert ((r > 200) & (g > 140) & (b < 155) & (r-g > 20) & (g-b > 35)).mean() >= .9, '159-S2 must sit on clear sand'
                assert np.linalg.norm(nodes - secrets['1002'], axis=1).min() >= 170
                # Height-fit camera: last level plus half of a 4:1 viewport.
                assert image.width - nodes[-1, 0] - image.height * 4 / 2 >= 200
                print('Landscape: all 175 levels and 3 secrets clear of water; 159-S2 on sand; 4:1 end-view margin >=200px')
        rectangles = table(layout, f'world_map_scene_{orientation}').reshape(-1, 4)
        assert len(rectangles) == expected
        previous = None
        axis = 1 if orientation == 'portrait' else 0
        intervals = []
        for index, scene in enumerate(data['scenes']):
            tile = scene[orientation]
            x, y, w, h = tile['world_bounds_before_zoom']
            assert max(w, h) <= 1086
            assert np.array_equal(rectangles[index], [x, y, w, h])
            assert tile['path'] in view
            with Image.open(ROOT / tile['path']) as crop:
                assert crop.size == (w, h) == tuple(tile['size'])
            start = [x, y][axis]
            intervals.append((start, start + [w, h][axis]))
        for start, end in sorted(intervals):
            if previous is None:
                assert start == 0
            else:
                assert previous - start == 128
            previous = end
        assert previous == source['size'][axis]
    print('Validated source coverage, 128px overlaps, tile limits and all 36 rail groups per orientation')
    paved_failures = sum('off paved pixels' in failure for failure in failures)
    print(f'Paved centers: {350 - paved_failures}/350')
    if failures:
        print(f'FAIL: {len(failures)} spacing/paving/tile violations', file=sys.stderr)
        for failure in failures[:24]:
            print(failure, file=sys.stderr)
        if len(failures) > 24:
            print(f'... {len(failures)-24} further violations', file=sys.stderr)
        return 1
    print('World map spacing local test passed: all edges, paved centers, 36 rail groups and dynamic tiles')
    return 0


if __name__ == '__main__':
    sys.exit(main())
