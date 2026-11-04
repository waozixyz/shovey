#!/usr/bin/env python3
"""Crop the joined paintings and regenerate native map geometry. Never edits sources.

python3 scripts/tile_world_map.py --version 5                # place levels on the authored graph
python3 scripts/tile_world_map.py --version 5 --write-graph  # first re-derive arm level counts
Road guides are waypoints on 30% previews. A shortest path over the visible
paving joins them, and every connection gets a near-equal road and straight
step in each orientation. Fork entries and merges stay on the painted junctions.
"""
from collections import defaultdict
import itertools
import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, binary_dilation, distance_transform_edt, gaussian_filter1d
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'work/world-map-source'
DEST = ROOT / 'assets/shovey/world-map'
# Keep 37 shared scenes after the sea extension; portrait crops stay identical.
SECTION_STEP = 830
SECTION_OVERLAP = 128
MAX_TILE_SIZE = 1086
# Lossy WebP quality for every game tile (method 6). The one setting to change.
TILE_QUALITY = 75
PREVIEW = .3
SMOOTHING = 4                  # traced samples; removes the pixel staircase
JUNCTION_SHIFTS = range(-40, 41, 10)  # native px a fork node may move within its junction
JUNCTION_HYSTERESIS = .005    # a re-export keeps recorded junctions unless the search beats them by this
RAIL_GROUP = 5
RAIL_GROUPS = 36
WORLD_MAP_LEVELS = 175


def section_count(extents):
    # Use one shared scene index space for both orientations. The shorter
    # painting gets smaller sections; neither orientation exceeds the target.
    return max(1, *(math.ceil((extent - SECTION_OVERLAP) / SECTION_STEP) for extent in extents))


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def table(text, name):
    m = re.search(r'\b'+name+r':\s*\[\d+\]\w+\s*=\s*\.\[(.*?)\];', text, re.S)
    return [float(v) for v in re.sub(r'//[^\n]*', '', m[1]).split(',') if v.strip()]


def replace_table(text, name, values):
    rows = [', '.join(f'{v:.3f}' for v in values[i:i+8]) for i in range(0,len(values),8)]
    declaration = f'{name}: [{len(values)}]float32 = .[\n    '+',\n    '.join(rows)+'\n];'
    return re.sub(r'\b'+name+r':\s*\[\d+\]\w+\s*=\s*\.\[.*?\];', lambda m: declaration, text, flags=re.S)


def sample(points, distances):
    points = np.asarray(points)
    cumulative = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    return np.column_stack([np.interp(distances,cumulative,points[:,axis]) for axis in range(2)])


def paved_mask(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (r > 165) & (g > 105) & (b > 55) & (r - g > 4) & (g - b > 12) & (r - b > 40)


def paved_fraction(rgb, point):
    x, y = map(round, point)
    return paved_mask(rgb[y-3:y+4, x-3:x+4].astype(np.int16)).mean()


def route_lengths(roads):
    return np.array([np.linalg.norm(np.diff(road, axis=0), axis=1).sum() for road in roads])


def cut(road, a, b):
    cumulative = np.r_[0, np.cumsum(np.linalg.norm(np.diff(road, axis=0), axis=1))]
    return np.vstack([sample(road, [a]), road[(cumulative > a) & (cumulative < b)], sample(road, [b])])


def smooth(road):
    result = np.column_stack([gaussian_filter1d(road[:, axis], SMOOTHING, mode='nearest') for axis in range(2)])
    result[0], result[-1] = road[0], road[-1]
    return result


class RoadTracer:
    """Shortest paths over the painted paving, preferring the road center.

    Unlike a window around each guide, the whole connected road is searchable,
    so a missing or moved bend can never send the route through scenery.
    """
    def __init__(self, image):
        paved = binary_closing(paved_mask(np.asarray(image).astype(np.int16)), iterations=1)
        self.depth = distance_transform_edt(paved)
        near = binary_dilation(paved, iterations=4)
        cost = np.where(paved, 1 + 20 / (1 + self.depth) ** 2, 80.0)
        h, w = paved.shape
        self.index = -np.ones((h, w), dtype=np.int64)
        self.ys, self.xs = np.nonzero(near)
        self.index[self.ys, self.xs] = np.arange(len(self.ys))
        rows, cols, weights = [], [], []
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            x2, y2 = self.xs + dx, self.ys + dy
            inside = (x2 >= 0) & (x2 < w) & (y2 >= 0) & (y2 < h)
            a = self.index[self.ys[inside], self.xs[inside]]; b = self.index[y2[inside], x2[inside]]
            keep = b >= 0
            weight = (cost[self.ys[inside][keep], self.xs[inside][keep]] +
                      cost[y2[inside][keep], x2[inside][keep]]) * .5 * math.hypot(dx, dy)
            rows += [a[keep], b[keep]]; cols += [b[keep], a[keep]]; weights += [weight, weight]
        self.graph = coo_matrix((np.concatenate(weights), (np.concatenate(rows), np.concatenate(cols))),
                                shape=(len(self.ys),) * 2).tocsr()
        _, self.component = connected_components(self.graph, directed=False)

    def snap(self, point, radius=8):
        x, y = map(round, point); h, w = self.depth.shape
        lo, hi = max(0, y - radius), min(h, y + radius + 1); left, right = max(0, x - radius), min(w, x + radius + 1)
        yy, xx = np.mgrid[lo:hi, left:right]
        score = self.depth[lo:hi, left:right] - .18 * np.hypot(xx - x, yy - y)
        score[self.index[lo:hi, left:right] < 0] = -np.inf
        iy, ix = np.unravel_index(np.argmax(score), score.shape)
        assert self.depth[lo + iy, left + ix] >= 1, ('guide point off the paving', point)
        return left + ix, lo + iy

    def path(self, a, b):
        source, target = self.index[a[1], a[0]], self.index[b[1], b[0]]
        assert self.component[source] == self.component[target], ('guide points on separate paving', a, b)
        # Bound the search near the pair first; a long detour falls back to the full road.
        for limit in (8 * math.dist(a, b) + 400, np.inf):
            _, previous = dijkstra(self.graph, indices=source, return_predecessors=True, limit=limit)
            if previous[target] >= 0: break
        result = [target]
        while result[-1] != source:
            result.append(previous[result[-1]])
        result = result[::-1]
        return np.column_stack((self.xs[result], self.ys[result])).astype(float)

    def trace(self, guides):
        shared = {}; traced = []
        for route in guides:
            anchors = [shared.setdefault(tuple(p), self.snap(p)) for p in route['points']]
            points = [anchors[0]]
            for a, b in zip(anchors, anchors[1:]):
                points.extend(map(tuple, self.path(a, b)[1:]))
            # Erase any excursion which revisits a pixel, so no node doubles back.
            simple = []; seen = {}
            for point in points:
                if point in seen:
                    keep = seen[point] + 1
                    for old in simple[keep:]: del seen[old]
                    simple = simple[:keep]
                else:
                    seen[point] = len(simple); simple.append(point)
            traced.append(np.asarray(simple, dtype=float))
        return traced


def graph_routes(edges, forks):
    """Split the authored graph into main stretches and fork arms, in road order."""
    successors = defaultdict(list)
    for a, b in edges: successors[a].append(b)
    entries = {fork[0]: fork for fork in forks}
    routes = []; main = [1]
    while True:
        current = main[-1]
        if current in entries:
            entry, left, right, merge, _ = entries[current]
            routes.append(main)
            for first in (left, right):
                arm = [entry, first]
                while arm[-1] != merge:
                    (following,) = successors[arm[-1]]; arm.append(following)
                routes.append(arm)
            main = [merge]
        elif successors[current]:
            (following,) = successors[current]; main.append(following)
        else:
            routes.append(main)
            return routes


def canonical_graph(counts):
    """Stable numbered boards: each main stretch, then the left and right arms."""
    edges = []; forks = []; current = 1
    for index in range(0, len(counts), 3):
        edges += [(level, level + 1) for level in range(current, current + counts[index])]
        current += counts[index]
        if index + 1 < len(counts):
            entry, left, right = current, counts[index + 1], counts[index + 2]
            merge = entry + left + right - 1
            for arm in (list(range(entry + 1, entry + left)), list(range(entry + left, merge))):
                path = [entry] + arm + [merge]; edges += list(zip(path, path[1:]))
            forks.append((entry, entry + 1, entry + left, merge, 0)); current = merge
    return sorted(edges), forks


def choose_counts(lengths_by_orientation, total):
    """Connections per route, so each step is close to the edge-weighted median.

    Arms need at least one board. All orientations share the chosen graph.
    """
    average = sum(sum(lengths) for lengths in lengths_by_orientation) / (len(lengths_by_orientation) * total)
    base = np.rint(np.mean(lengths_by_orientation, axis=0) / average).astype(int)
    best = None
    for counts in itertools.product(*[range(max(1, b - 2), b + 3) for b in base]):
        if sum(counts) != total or any(counts[i] < 2 for i in range(len(counts)) if i % 3): continue
        worst = 0
        for lengths in lengths_by_orientation:
            steps = np.repeat(np.asarray(lengths) / counts, counts)
            worst = max(worst, np.abs(steps / np.median(steps) - 1).max())
        if best is None or worst < best[0]: best = (worst, counts)
    return list(best[1])


def display_numbers(edges, forks):
    """Main journey numbers: both arms of a fork share one number."""
    routes = graph_routes(edges, forks); numbers = {}; number = 0
    for index, route in enumerate(routes):
        if index % 3 == 0:
            for level in route:
                number += 1; numbers[level] = str(number)
        else:
            side = 'A' if index % 3 == 1 else 'B'
            for step, level in enumerate(route[1:-1], 1): numbers[level] = f'{number + 1}-{side}{step}'
            if index % 3 == 2: number += 1
    return numbers


def write_graph(path, counts):
    edges, forks = canonical_graph(counts)
    text = path.read_text()
    text = re.sub(r'WORLD_MAP_FORK_COUNT :: \d+', f'WORLD_MAP_FORK_COUNT :: {len(forks)}', text)
    text = re.sub(r'WORLD_MAP_EDGE_COUNT :: \d+', f'WORLD_MAP_EDGE_COUNT :: {len(edges)}', text)
    rows = ''.join(f'    {", ".join(map(str, fork))},\n' for fork in forks)
    text = re.sub(r'world_map_forks: \[\d+\]s32 = \.\[\n.*?\];', lambda m: f'world_map_forks: [{5 * len(forks)}]s32 = .[\n{rows}];', text, flags=re.S)
    rows = ''.join(f'    {a}, {b},\n' for a, b in edges)
    text = re.sub(r'world_map_edges: \[\d+\]s32 = \.\[\n.*?\];', lambda m: f'world_map_edges: [{2 * len(edges)}]s32 = .[\n{rows}];', text, flags=re.S)
    numbers = display_numbers(edges, forks)
    chest = int(re.search(r'CHEST_PARENT_LEVEL :: (\d+)', (ROOT / 'src/reward_locations.zi').read_text())[1])
    text = re.sub(r'(\.label = ifx level == CHEST_LEVEL then )"[^"]*"( else ifx level == 1001 then )"[^"]*"( else )"[^"]*"',
                  lambda m: f'{m[1]}"{numbers[chest]}-S"{m[2]}"{numbers[175]}-S1"{m[3]}"{numbers[175]}-S2"', text)
    path.write_text(text)
    return edges, forks


def place_route(road, count, chord_target, arc_target, resolution=2.0, window=.25):
    """Arc distances of count+1 nodes with fixed ends.

    Exact dynamic programming on a fine arc grid first minimizes the worst
    relative chord or arc error, then the squared error within that bound.
    A hairpin can then fall on a node instead of shortening a connection.
    """
    length = route_lengths([road])[0]
    m = max(count * 8, math.ceil(length / resolution)) + 1
    grid = np.linspace(0.0, length, m); spacing = grid[1]
    points = sample(road, grid)
    offsets = np.arange(max(1, math.floor(arc_target * (1 - window) / spacing)),
                        math.ceil(arc_target * (1 + window) / spacing) + 1)
    error = np.full((len(offsets), m), np.inf)
    for i, offset in enumerate(offsets):
        if offset >= m: continue
        chord = np.linalg.norm(points[offset:] - points[:-offset], axis=1)
        error[i, offset:] = np.maximum(np.abs(chord / chord_target - 1), abs(offset * spacing / arc_target - 1))
    def solve(cost, combine):
        best = np.full(m, np.inf); best[0] = 0.0; choices = []
        for _ in range(count):
            new = np.full(m, np.inf); choice = np.zeros(m, dtype=np.int64)
            for i, offset in enumerate(offsets):
                if offset >= m: continue
                candidate = combine(np.r_[np.full(offset, np.inf), best[:-offset]], cost[i])
                better = candidate < new; new[better] = candidate[better]; choice[better] = offset
            choices.append(choice); best = new
        return best, choices
    bottleneck, _ = solve(error, np.maximum)
    own = length / count
    if not np.isfinite(bottleneck[-1]) and abs(own / arc_target - 1) > window:
        # This painted route is far shorter or longer than its board count
        # needs; divide it evenly on its own step and report the deviation.
        return place_route(road, count, chord_target * own / arc_target, own, resolution, window)
    assert np.isfinite(bottleneck[-1]), ('route cannot be divided', count, length)
    total, choices = solve(np.where(error <= max(bottleneck[-1], .03) + 1e-9, error ** 2, np.inf), np.add)
    index = m - 1; nodes = [index]
    for choice in reversed(choices):
        index -= choice[index]; nodes.append(index)
    assert index == 0
    return grid[nodes[::-1]]


def move_junctions(routes, shifts):
    """Move fork nodes inside their painted junctions.

    A positive shift slides the node along the shared main road; a negative
    one moves it into the junction mouth, midway between both arms.
    """
    routes = list(routes); length = lambda road: route_lengths([road])[0]
    for fork in range(len(routes) // 3):
        before, left, right, after = 3 * fork, 3 * fork + 1, 3 * fork + 2, 3 * fork + 3
        main0, a, b, main1 = routes[before], routes[left], routes[right], routes[after]
        entry, merge = shifts[2 * fork], shifts[2 * fork + 1]
        if entry > 0:
            stem = cut(main0, length(main0) - entry, length(main0)); main0 = cut(main0, 0, length(main0) - entry)
            a = np.vstack([stem, a[1:]]); b = np.vstack([stem, b[1:]])
        elif entry < 0:
            node = (sample(a, [-entry])[0] + sample(b, [-entry])[0]) / 2
            main0 = np.vstack([main0, node])
            a = np.vstack([node, cut(a, -entry, length(a))[1:]]); b = np.vstack([node, cut(b, -entry, length(b))[1:]])
        if merge > 0:
            stem = cut(main1, 0, merge); main1 = cut(main1, merge, length(main1))
            a = np.vstack([a, stem[1:]]); b = np.vstack([b, stem[1:]])
        elif merge < 0:
            node = (sample(a, [length(a) + merge])[0] + sample(b, [length(b) + merge])[0]) / 2
            main1 = np.vstack([node, main1])
            a = np.vstack([cut(a, 0, length(a) + merge)[:-1], node]); b = np.vstack([cut(b, 0, length(b) + merge)[:-1], node])
        routes[before], routes[left], routes[right], routes[after] = main0, a, b, main1
    return routes


def junction_node(routes, fork, merge):
    return routes[3 * fork + 3][0] if merge else routes[3 * fork][-1]


def place_levels(roads, counts, rgb, recorded=None):
    """Search junction positions, then place every route against shared medians.

    The previous export's junction shifts are kept unless the search is clearly
    better, so a pixel-level retrace never reshuffles the forks.
    """
    def evaluate(shifts):
        routes = move_junctions(roads, shifts)
        for fork in range(len(roads) // 3):
            for merge in (0, 1):
                if paved_fraction(rgb, junction_node(routes, fork, merge)) < .8: return float('inf'), None
        lengths = route_lengths(routes)
        arc = np.median(np.repeat(lengths / counts, counts)); chord = .97 * arc
        for _ in range(3):
            placed = [place_route(road, count, chord, arc) for road, count in zip(routes, counts)]
            chords = np.concatenate([np.linalg.norm(np.diff(sample(road, along), axis=0), axis=1)
                                     for road, along in zip(routes, placed)])
            arcs = np.concatenate([np.diff(along) for along in placed])
            chord, arc = np.median(chords), np.median(arcs)
        worst = max(np.abs(chords / chord - 1).max(), np.abs(arcs / arc - 1).max())
        return worst, (routes, placed)
    shifts = [0] * (2 * (len(roads) // 3)); best = evaluate(shifts)
    for _ in range(2):
        for junction in range(len(shifts)):
            for value in JUNCTION_SHIFTS:
                trial = shifts[:junction] + [value] + shifts[junction + 1:]
                result = evaluate(trial)
                if result[0] < best[0] - 1e-6: best, shifts = result, trial
    if recorded is not None and len(recorded) == len(shifts) and list(recorded) != shifts:
        kept = evaluate(list(recorded))
        if kept[0] <= best[0] + JUNCTION_HYSTERESIS: best, shifts = kept, list(recorded)
    return best[0], shifts, *best[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',type=int)
    parser.add_argument('--write-graph',action='store_true',help='re-derive arm level counts from measured roads')
    args=parser.parse_args()
    def source(orientation,version): return SOURCE/f'start-to-boat-{ "landscape-" if orientation=="landscape" else ""}joined-v{version}.png'
    version=args.version or max(v for v in range(5,10) if all(source(o,v).exists() for o in ('portrait','landscape')))
    guides=json.loads((ROOT/'scripts/world_map_roads.json').read_text())
    previous_data=json.loads((DEST/'scenes.json').read_text()) if (DEST/'scenes.json').exists() else {}
    # An art-only extension must not reflow existing levels or their rails.
    preserve_geometry=guides.get('preserve_geometry',False) and not args.write_graph
    if preserve_geometry:
        assert previous_data.get('source_version')==version, 'art-only export needs existing geometry for this source version'
    layout_path=ROOT/'src/world_map_layout.zi';layout=layout_path.read_text()
    graph_path=ROOT/'src/world_map_progression.zi'
    extents = []
    for orientation in ('portrait', 'landscape'):
        with Image.open(source(orientation, version)) as image:
            extents.append(image.height if orientation == 'portrait' else image.width)
    count = section_count(extents)
    data={'schema':3,'source_version':version,'generator':'scripts/tile_world_map.py','overlap_native_pixels':SECTION_OVERLAP,'section_step_native_pixels':SECTION_STEP,'scenes':[{'index':i} for i in range(count)],'sources':{},'world_bounds_before_zoom':{},'nodes':{},'roads':{},'spacing':{}}
    images={};roads={}
    for orientation in ('portrait','landscape'):
        src=source(orientation,version); image=Image.open(src).convert('RGB');w,h=image.size;images[orientation]=image
        data['sources'][orientation]={'path':str(src.relative_to(ROOT)),'sha256':digest(src),'size':[w,h]}
        data['world_bounds_before_zoom'][orientation]=[0,0,w,h]
        expected_size=guides.get('source_sizes',{}).get(orientation)
        if expected_size: assert [w,h]==expected_size, (orientation,'source size',image.size,expected_size)
        if preserve_geometry:
            data['roads'][orientation]=previous_data['roads'][orientation]
            roads[orientation]=data['roads'][orientation]
            continue
        preview=image.resize((round(w*PREVIEW),round(h*PREVIEW)),Image.Resampling.LANCZOS)
        if orientation=='landscape':preview=preview.transpose(Image.Transpose.ROTATE_270)
        traced=RoadTracer(preview).trace(guides[orientation])
        data['roads'][orientation]=[r.tolist() for r in traced] # preview-coordinate evidence for regeneration
        if orientation=='landscape': traced=[np.column_stack((r[:,1]/PREVIEW,(preview.width-1-r[:,0])/PREVIEW)) for r in traced]
        else: traced=[r/PREVIEW for r in traced]
        roads[orientation]=[smooth(r) for r in traced]
    if args.write_graph:
        routes=len(guides['portrait']); total=WORLD_MAP_LEVELS-1+routes//3
        counts=choose_counts([route_lengths(roads[o]) for o in roads],total)
        write_graph(graph_path,counts)
    graph=graph_path.read_text();flat=table(graph,'world_map_edges');edges=list(zip(map(int,flat[::2]),map(int,flat[1::2])))
    forks=np.array(table(graph,'world_map_forks'),dtype=int).reshape(-1,5).tolist()
    route_ids=graph_routes(edges,forks);counts=np.array([len(ids)-1 for ids in route_ids])
    assert all(len(roads[o])==len(route_ids) for o in roads),('road guides do not match the graph routes',len(route_ids))
    assert len(edges)<=RAIL_GROUP*RAIL_GROUPS
    paths={};bounds={}
    previous=previous_data.get('spacing',{}) if not args.write_graph else {}
    for orientation in ('portrait','landscape'):
        image=images[orientation];w,h=image.size;rgb=np.asarray(image)
        positions={};rails={}
        if preserve_geometry:
            positions={i:np.array(point) for i,point in enumerate(previous_data['nodes'][orientation],1)}
            name='world_map_landscape_positions' if orientation=='landscape' else 'world_map_positions'
            assert np.array_equal(np.array(table(layout,name)).reshape(-1,2),list(positions.values()))
            points=np.concatenate([table(layout,f'world_map_rail_{orientation}{group}') for group in range(RAIL_GROUPS)]).reshape(-1,33,2)
            rails=dict(zip(edges,points))
            shifts=previous[orientation]['junction_shifts_native_px']
            worst=previous[orientation]['worst_relative_error']
        else:
            worst,shifts,routes,placed=place_levels(roads[orientation],counts,rgb,previous.get(orientation,{}).get('junction_shifts_native_px'))
            for ids,road,along in zip(route_ids,routes,placed):
                for identity,point in zip(ids,sample(road,along)):
                    if identity in positions: assert math.dist(positions[identity],point)<.01,(orientation,identity)
                    positions[identity]=point
                for index,(a,b) in enumerate(zip(ids,ids[1:])):rails[a,b]=sample(road,np.linspace(along[index],along[index+1],33))
        assert len(positions)==WORLD_MAP_LEVELS and set(rails)==set(edges)
        for level,point in positions.items():
            assert paved_fraction(rgb,point)>=.6,('level off the paving',orientation,level,point.round(1).tolist())
        data['nodes'][orientation]=[positions[i].round(3).tolist() for i in range(1,WORLD_MAP_LEVELS+1)]
        gaps=[math.dist(data['nodes'][orientation][a-1],data['nodes'][orientation][b-1]) for a,b in edges]
        data['spacing'][orientation]={'junction_shifts_native_px':shifts,'worst_relative_error':round(float(worst),4),
            'gap_min_median_max':[round(float(v),3) for v in (min(gaps),np.median(gaps),max(gaps))]}
        print(f'{orientation}: counts {counts.tolist()}, junction shifts {shifts}, gaps min/median/max '
              f'{min(gaps):.1f}/{np.median(gaps):.1f}/{max(gaps):.1f} art px, worst {worst:.3f}')
        layout=replace_table(layout,'world_map_landscape_positions' if orientation=='landscape' else 'world_map_positions',np.array(data['nodes'][orientation]).flatten())
        for group in range(RAIL_GROUPS):
            values=np.concatenate([rails[e] for e in edges[group*RAIL_GROUP:(group+1)*RAIL_GROUP]]).flatten()
            layout=replace_table(layout,f'world_map_rail_{orientation}{group}',values)
        extent=h if orientation=='portrait' else w
        step=math.ceil((extent-SECTION_OVERLAP)/count);rectangles=[];paths[orientation]=[]
        # Identical 128px overlap, each edge remains at the original source coordinate.
        for i in range(count):
            start=i*step;end=min(extent,start+step+SECTION_OVERLAP)
            box=(0,h-end,w,h-start) if orientation=='portrait' else (start,0,end,h)
            crop=image.crop(box)
            assert max(crop.size) <= MAX_TILE_SIZE, (orientation, crop.size)
            pixels=np.asarray(crop).astype(np.uint16)
            crop=Image.fromarray(np.minimum(255,((pixels+4)//8)*8).astype('uint8'))
            name=f'continuous-{i:02d}-{orientation}.webp';target=DEST/name
            crop.save(target,'WEBP',quality=TILE_QUALITY,method=6)
            rectangle=[box[0],box[1],box[2]-box[0],box[3]-box[1]];rectangles.extend(rectangle)
            data['scenes'][i][orientation]={'path':str(target.relative_to(ROOT)),'size':list(crop.size),'world_bounds_before_zoom':rectangle,'sha256':digest(target),'bytes':target.stat().st_size}
            paths[orientation].append(str(target.relative_to(ROOT)))
        bounds[orientation]=(w,h)
        # A shorter source leaves no tiles from an earlier, longer export.
        for stale in DEST.glob(f'continuous-*-{orientation}.webp'):
            if int(stale.name.split('-')[1])>=count: stale.unlink()
        layout=replace_table(layout,f'world_map_scene_{orientation}',rectangles)
    w,h=bounds['portrait']; lw,lh=bounds['landscape']
    layout=re.sub(r'(WorldMapWorldBounds :: .*?\n)(.*?)(\n})',lambda m:m[1]+f'    scale: float32 = WorldMapWorldZoom\n    if landscape {{ return Rectangle.{{0.0,0.0,{lw}.0 * scale,{lh}.0 * scale}} }}\n    return Rectangle.{{0.0,0.0,{w}.0 * scale,{h}.0 * scale}}'+m[3],layout,count=1,flags=re.S)
    # Keep source geometry and native dimensions separate from screen zoom.
    minimum=min(math.dist(a,b) for nodes in data['nodes'].values() for i,a in enumerate(nodes) for b in nodes[i+1:])
    zoom=max(1.3,math.ceil(80.2/minimum*100)/100)
    layout=re.sub(r'WorldMapWorldZoom :: [\d.]+;',f'WorldMapWorldZoom :: {zoom};',layout)
    layout=re.sub(r'WorldMapSceneCount :: \d+;', f'WorldMapSceneCount :: {count};', layout)
    layout=re.sub(r'edge >= \d+ \|\| sample', f'edge >= {len(edges)} || sample', layout)
    layout_path.write_text(layout)
    view_path=ROOT/'src/world_map_view.zi';view=view_path.read_text()
    mapping = '    if landscape {\n'
    for i, path in enumerate(paths['landscape']):
        mapping += f'        if section == {i} {{ path = "{path}" }}\n'
    mapping += '    } else {\n'
    for i, path in enumerate(paths['portrait']):
        mapping += f'        if section == {i} {{ path = "{path}" }}\n'
    mapping += '    }\n'
    view=re.sub(r'(WorldMapViewSection :: .*?\n    path: string\n).*?(    scene :=)',
                lambda m: m[1]+mapping+m[2], view, count=1, flags=re.S)
    view=re.sub(r'(return \(ifx props.landscape then viewport.height else viewport.width\) / )[^\n]+',
                lambda m: m[1]+f'(ifx props.landscape then {lh}.0 else {w}.0)', view)
    if preserve_geometry:
        # The shared scene count and cross-axis dimensions are unchanged.
        # Do not touch the view while another task works on its avatar drawing.
        assert count==len(previous_data['scenes'])
        assert all(path in view_path.read_text() for values in paths.values() for path in values)
        assert w==previous_data['sources']['portrait']['size'][0] and lh==previous_data['sources']['landscape']['size'][1]
    else:
        view_path.write_text(view)
    if 'secret_offsets_native_pixels' in guides:
        data['secret_offsets_native_pixels']=guides['secret_offsets_native_pixels']
    (DEST/'scenes.json').write_text(json.dumps(data,indent=2)+'\n')
    art_path=ROOT/'assets/shovey/art.json';art=json.loads(art_path.read_text())
    art['files']=[e for e in art['files'] if not(e['path'].startswith('world-map/') and e['path'].endswith('.webp'))]
    for scene in data['scenes']:
        for orientation in paths:
            asset=scene[orientation];art['files'].append({'path':asset['path'].removeprefix('assets/shovey/'),'depicts':f'Continuous {orientation} world map tile {scene["index"]}, joined source v{version}','sha256':asset['sha256']})
    art_path.write_text(json.dumps(art,indent=2)+'\n')
    print(f'Exported source v{version}: {count * 2} WebP tiles at quality {TILE_QUALITY}, minimum native center distance {minimum:.2f}, world zoom {zoom}')

if __name__=='__main__': main()
