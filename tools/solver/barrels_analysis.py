#!/usr/bin/env python3
"""Bounded reproducible campaign comparison, using only the real engine solver.

Run through build-queue. Stumps reproduce the old solid barrel decoration:
its only old behavior was blocking floor, shots and beams. No alternate
engine or source checkout is needed. Search limits are explicit in the report.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOLVER = ROOT / 'build/solver/shovey-solve-classic'


def board(level, legacy=False):
    layers = [list(level[k]) for k in ('cells', 'tiles', 'decorations')]
    if legacy:
        # Old engine rejected 141 in cells; original boards use decorations.
        layers[2] = [''.join('8e' if row[i:i+2] == '8d' else row[i:i+2]
                            for i in range(0, len(row), 2)) for row in layers[2]]
    return ''.join(''.join(layer) for layer in layers)


def call(command, number, data, *args):
    return subprocess.run([str(SOLVER), command, '--level', str(number), *args, data],
                          capture_output=True, text=True, timeout=40)


def proof(number, data, route):
    run = subprocess.run([str(SOLVER), 'explain', '--level', str(number), data, route],
                         capture_output=True, text=True, timeout=20)
    return json.loads(run.stdout) if run.returncode == 0 else None


def search(number, data, seconds, method):
    run = call('solve', number, data, '--only', method, '--seconds', str(seconds),
               '--max-states', '350000', '--max-mb', '96')
    stats = next((json.loads(s[6:]) for s in run.stderr.splitlines() if s.startswith('stats ')), {})
    return dict(method=method, seconds=seconds, stats=stats, route=run.stdout.strip() if run.returncode == 0 else None)


def compare_routes(row, level):
    """Apply each found route to both profiles, separating shortcuts from search noise."""
    old, new = row['old'], row['new']
    if not row['affected']:
        return
    for source, target, legacy in [(old, new, False), (new, old, True)]:
        if not source['route']:
            continue
        replay = proof(row['number'], board(level, legacy), source['route'])
        current = target['proof']
        if replay and (not current or (replay['pushes'], replay['moves']) < (current['pushes'], current['moves'])):
            target.update(route=source['route'], proof=replay, method='cross-replay')
    row['new_route_works_old'] = bool(new['route'] and proof(row['number'], board(level, True), new['route']))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--baseline', default='work/barrels-campaign-before.json')
    parser.add_argument('--seconds', type=float, default=2)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--refine', action='store_true', help='add greedy searches to existing affected comparisons')
    args = parser.parse_args()
    levels = json.loads((ROOT / args.baseline).read_text())['levels']
    dest = ROOT / 'work/barrels-sweep.jsonl'
    done = {}
    if args.resume and dest.exists():
        for line in dest.read_text().splitlines():
            row = json.loads(line)
            done[row['number']] = row
    if args.refine:
        rows = [json.loads(line) for line in dest.read_text().splitlines()]
        for row in rows:
            if not row['affected']:
                continue
            level = levels[row['number'] - 1]
            for label in ('old', 'new'):
                value = board(level, label == 'old')
                result = search(row['number'], value, args.seconds, 'greedy')
                row[label]['searches'].append(result)
                if result['route']:
                    replay = proof(row['number'], value, result['route'])
                    current = row[label]['proof']
                    if replay and (not current or (replay['pushes'], replay['moves']) < (current['pushes'], current['moves'])):
                        row[label].update(route=result['route'], proof=replay, method='greedy')
            compare_routes(row, level)
            print('refined', row['number'], 'old', (row['old']['proof']['moves'], row['old']['proof']['pushes']), 'new', (row['new']['proof']['moves'], row['new']['proof']['pushes']), 'old-compatible', row.get('new_route_works_old'), flush=True)
            # Persist each result so an interrupted sweep can be audited.
            dest.write_text(''.join(json.dumps(item) + '\n' for item in rows))
        done = {row['number']: row for row in rows}
        args.resume = True
    with dest.open('a' if args.resume else 'w') as output:
        for level in levels:
            n = level['number']
            if n in done:
                continue
            data, old = board(level), board(level, True)
            affected = data != old
            row = dict(number=n, affected=affected)
            for label, value in [('old', old), ('new', data)]:
                if label == 'new' and not affected:
                    row[label] = row['old']
                    continue
                stored = proof(n, value, level['solution'])
                searches = [search(n, value, args.seconds, 'bfs')]
                if not searches[0]['route']:
                    searches.append(search(n, value, args.seconds, 'macro-bfs'))
                candidates = [(item['route'], proof(n, value, item['route']), item['method'])
                              for item in searches if item['route']]
                candidates = [item for item in candidates if item[1]]
                if stored:
                    candidates.append((level['solution'], stored, 'published'))
                best = min(candidates, key=lambda item: (item[1]['moves'], item[1]['pushes'])) if candidates else None
                row[label] = dict(searches=searches, stored_replays=bool(stored),
                                  route=best[0] if best else None, proof=best[1] if best else None,
                                  method=best[2] if best else None,
                                  move_optimal=bool(searches[0]['route']))
            compare_routes(row, level)
            output.write(json.dumps(row) + '\n')
            output.flush()
            a,b=row['old'],row['new']
            print(n, 'barrels' if affected else 'identical graph',
                  (a['proof']['moves'],a['proof']['pushes']) if a['proof'] else 'unknown',
                  (b['proof']['moves'],b['proof']['pushes']) if b['proof'] else 'unknown',flush=True)
    rows=[json.loads(line) for line in dest.open()]
    lines=['# Movable barrels: campaign comparison', '',
           'Barrels formerly were blocking scenery, with no separate interaction. They now retain kind 141 '
           'and share crate pushes, marks, buttons, water bridges, shots, save/restore and animation layers.', '',
           f'Every level was searched under both rules (identical boards without barrels reuse the same exact state graph). '
           'The initial BFS/macro BFS pass uses 2s per search; targeted greedy refinement uses 3s. '
           'Each search caps 350,000 states and 96 MiB. '
           'BFS proves the shortest input-action route when it finishes (the displayed move counter omits rejected turns). Macro BFS minimizes state-changing actions; '
           'on ordinary Sokoban these are pushes. Published routes are replayed as fallback upper bounds. '
           'A bound is never presented as a proven optimum. Search states/expanded are a reproducible branching proxy, '
           'not a player difficulty score.', '',
           'Old-rule comparison replaces each barrel decoration with a stump (the same solid-decoration behavior). '
           'Levels 93, 97 and 98 belong to the forest redesign task and are not edited here.', '',
           '| Level | Barrels | Old moves/pushes | New moves/pushes | Proof old/new | BFS states old/new |',
           '|---|---|---|---|---|---|']
    for row in rows:
        compare_routes(row, levels[row['number'] - 1])
        a,b=row['old'],row['new']
        metric=lambda v: f"{v['proof']['moves']}/{v['proof']['pushes']}" if v['proof'] else 'unresolved'
        status=lambda v: 'BFS action optimum found' if v['move_optimal'] else f"bound ({v['method']})"
        state=lambda v: str(v['searches'][0]['stats'].get('states','?'))
        lines.append(f"| {row['number']} | {'yes' if row['affected'] else 'no'} | {metric(a)} | {metric(b)} | {status(a)} / {status(b)} | {state(a)} / {state(b)} |")
    lines+=['','## Candidates for review','']
    for row in rows:
        a,b=row['old']['proof'],row['new']['proof']
        if row['affected'] and a and b and (b['moves'] < a['moves'] or b['pushes'] < a['pushes']):
            lines.append(f"- Level {row['number']}: {a['moves']}→{b['moves']} moves, {a['pushes']}→{b['pushes']} pushes. Review proof events before deciding whether a shortcut is unintended.")
    (ROOT / 'work/barrels-analysis.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    main()
