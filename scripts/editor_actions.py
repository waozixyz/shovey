#!/usr/bin/env python3
"""Editor actions. Model changes must win in the real engine."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / 'backup/editor-drafts'
SOLVER = ROOT / 'build/solver/shovey-solve-classic'
LAYERS = ('cells', 'tiles', 'decorations')
COSMETIC = {0, 57, 58, 59, 60, 61, 77, 78, *range(99, 104)}
WALLS = {12, 62, 63, 76, 95, 96, 97, 98}
MOSS_WALLS = {14, *range(127, 131)}
DOORS = {104, 105, *range(116, 122)}
ALLOWED = (
    ({0, *range(1, 77), *range(82, 135)} - {22, 24, 32, 41, 42, 43}),
    {0, 4, 5, 6, 12, 14, 47, 48, 49, *range(57, 72), 76, 77, 78, *range(95, 104), *range(127, 131)},
    {0, 57, 58, 59, 84, 106, 122, *range(135, 143)},
)
BLOCKING_DECORATIONS = {84, 106, 122, *range(139, 143)}


def atomic(path, text):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(text)
    temporary.replace(path)


def board_hex(level):
    cells = ''.join(level['cells'])
    defaults = []
    for i in range(0, 480, 2):
        kind = int(cells[i:i + 2], 16)
        tile = kind if kind in {0, 4, 5, 6, 12, 14, 47, 48, 49, 60, 61, 63, 64, 65, 70, 76, 77, 78, *range(95, 104), *range(127, 131)} else 77 if kind == 7 else 64 if 89 <= kind <= 91 else 12 if kind == 62 else 0
        defaults.append(f'{tile:02x}')
    return cells + (''.join(level.get('tiles', [])) or ''.join(defaults)) + (''.join(level.get('decorations', [])) or '00' * 240)


def record(number, board, route):
    if not re.fullmatch('[0-9a-f]{1440}', board) or not re.fullmatch('[0123ft]+', route):
        raise ValueError('The saved board or winning route is incomplete')
    def rows(start):
        return [board[i:i + 24] for i in range(start, start + 480, 24)]
    return dict(number=number, cells=rows(0), tiles=rows(480), decorations=rows(960), solution=route)


def approve(number):
    request = (DRAFTS / f'{number:03}.approval-request').read_text().splitlines()
    level = record(number, request[0], request[1])
    path = ROOT / 'levels/approved.json'
    with (DRAFTS / 'approval.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = DRAFTS / f'{number:03}.approved'
        if marker.exists() and marker.read_text().strip() != request[0]:
            return  # A later click approved a newer layout while this waited.
        data = json.loads(path.read_text())
        approved = {item['number']: item for item in data['levels']}
        pending = {int(n): value for n, value in data.get('pending', {}).items()}
        pending[number] = level
        for n in sorted(pending):
            if n in approved or n == len(approved) + 1:
                approved[n] = pending.pop(n)
        data['levels'] = [approved[n] for n in sorted(approved)]
        data['pending'] = pending
        atomic(path, json.dumps(data, indent=1) + '\n')
        atomic(DRAFTS / f'{number:03}.approved', request[0])
    if not (ROOT / 'backup/editor-publish.json').is_file():
        atomic(DRAFTS / 'publish-status', 'Approved')
        return
    atomic(DRAFTS / 'publish-status', 'Updating…')
    subprocess.Popen([sys.executable, str(ROOT / 'scripts/publish-approved.py')], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def update(force=True):
    # Updating an approved campaign never depends on the open draft's proof.
    if not (ROOT / 'backup/editor-publish.json').is_file():
        atomic(DRAFTS / 'publish-status', 'Approved')
        return
    atomic(DRAFTS / 'publish-status', 'Updating…')
    subprocess.Popen([sys.executable, str(ROOT / 'scripts/publish-approved.py')] + (['--force'] if force else []), cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def update_all():
    if not (ROOT / 'backup/editor-publish.json').is_file():
        return
    with (DRAFTS / 'update-all.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        update_all_levels()


def update_all_levels():
    # The owner already approved these exact snapshots. Republish them without
    # searching drafts, rewriting approval records or consulting server state.
    approved = json.loads((ROOT / 'levels/approved.json').read_text())['levels']
    retained = {}
    for level in approved:
        draft = DRAFTS / f'{level["number"]:03}.hex'
        if draft.exists() and draft.read_text().strip() != board_hex(level):
            retained[str(level['number'])] = hashlib.sha256(draft.read_bytes().strip()).hexdigest()
    atomic(DRAFTS / 'update-all-summary.json', json.dumps(dict(
        updated=[level['number'] for level in approved], checked=[],
        kept_unproven_drafts=sorted(map(int, retained)), unproven_boards=retained), indent=2) + '\n')
    update(force=True)


def glm_settings():
    # Reuse Harmony's configured GLM provider; keys remain inside this process.
    settings = {}
    path = Path.home() / '.config/harmony/host/.env'
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.match(r'(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)', line.strip())
            if match:
                try:
                    values = shlex.split(match[2], comments=True)
                    settings[match[1]] = values[0] if values else ''
                except ValueError:
                    continue
    settings.update({key: value for key, value in os.environ.items() if key in ('GLM_BASE_URL', 'GLM_MODEL', 'GLM_API_KEY', 'ZAI_API_KEY')})
    key = settings.get('GLM_API_KEY') or settings.get('ZAI_API_KEY')
    if not key:
        raise ValueError('Configure a GLM API key.')
    model = settings.get('GLM_MODEL', 'glm-5.3')
    if 'glm' not in model.lower():
        raise ValueError('The configured model must be GLM')
    return settings.get('GLM_BASE_URL', 'https://api.z.ai/api/coding/paas/v4').rstrip('/'), key, model


def verify_route(number, board, route):
    if not isinstance(route, str) or not re.fullmatch('[0123ft]{1,60000}', route):
        return False
    verified = subprocess.run([str(SOLVER), 'verify', '--level', str(number), board, route],
                              cwd=ROOT, capture_output=True, timeout=10)
    return verified.returncode == 0


def existing_route(number, original):
    proof = DRAFTS / f'{number:03}.proof'
    if proof.exists():
        lines = proof.read_text().splitlines()
        if len(lines) == 2 and lines[0] == original and verify_route(number, original, lines[1]):
            return lines[1]
    for level in json.loads((ROOT / 'levels/classic.json').read_text())['levels']:
        if level['number'] == number and board_hex(level) == original:
            route = level.get('solution', '')
            if verify_route(number, original, route):
                return route
    return ''


def route_examples(number):
    path = DRAFTS / f'{number:03}.routes'
    lines = path.read_text().splitlines() if path.exists() else []
    examples = []
    for index in range(0, len(lines) - 1, 2):
        base, route = lines[index:index + 2]
        if re.fullmatch('[0-9a-f]{1440}', base) and re.fullmatch('[0123ft]{1,60000}', route):
            examples.append((base, route))
    return examples


def remember_route(number, board, route):
    proof = DRAFTS / f'{number:03}.proof'
    previous = proof.read_text().splitlines() if proof.exists() else []
    examples = [(board, route)]
    if len(previous) == 2 and re.fullmatch('[0-9a-f]{1440}', previous[0]) and re.fullmatch('[0123ft]{1,60000}', previous[1]):
        examples.append(tuple(previous))
    examples += route_examples(number)
    examples = list(dict.fromkeys(examples))[:8]
    atomic(DRAFTS / f'{number:03}.routes', ''.join(base + '\n' + moves + '\n' for base, moves in examples))


def learned_routes(number, board):
    examples = [(sum(base[at:at + 2] != board[at:at + 2] for at in range(0, 1440, 2)), index, route)
                for index, (base, route) in enumerate(route_examples(number))]
    return [route for _, _, route in sorted(examples)[:3]]


def apply_proposal(original, proposal, repair=False, mode='modify', partial=False):
    """Apply small, explicit landscape-coordinate edits to the supplied board."""
    if mode not in ('modify', 'redesign', 'prettify'):
        raise ValueError('Unknown GLM mode')
    if mode == 'redesign' and isinstance(proposal, dict) and 'edits' not in proposal:
        edits = []
        for layer, name in enumerate(LAYERS):
            grid = proposal.get(name)
            if not isinstance(grid, list) or len(grid) != 12 or any(not isinstance(row, list) or len(row) != 20 for row in grid):
                raise ValueError('Redesign needs three landscape grids, each 12 rows of 20 integer IDs')
            for y, row in enumerate(grid):
                for x, after in enumerate(row):
                    at = layer * 240 + 11 - y + x * 12
                    before = int(original[at * 2:at * 2 + 2], 16)
                    if type(after) is not int:
                        raise ValueError('Use integer piece IDs in every grid')
                    if after != before:
                        edits.append(dict(layer=name, x=x, y=y, **{'from': before, 'to': after}))
        proposal = proposal | dict(edits=edits)
    if not isinstance(proposal, dict) or not isinstance(proposal.get('edits'), list):
        raise ValueError('Return a JSON object with an edits list, not a replacement level')
    maximum = 720 if mode == 'redesign' else 480 if mode == 'prettify' else 80
    if not 1 <= len(proposal['edits']) <= maximum:
        raise ValueError(f'Use between 1 and {maximum} layer edits')
    cells = [int(original[i:i + 2], 16) for i in range(0, 1440, 2)]
    updated = cells.copy()
    touched = set()
    coordinates = set()
    for edit in proposal['edits']:
        if not isinstance(edit, dict) or edit.get('layer') not in (LAYERS if repair or mode != 'modify' else LAYERS[:2]):
            raise ValueError('Edit cells or tiles only; keep the existing decoration')
        x, y, before, after = (edit.get(key) for key in ('x', 'y', 'from', 'to'))
        if any(type(value) is not int for value in (x, y, before, after)) or not (0 <= x < 20 and 0 <= y < 12):
            raise ValueError('Each edit needs integer x (0–19), y (0–11), from and to')
        layer = LAYERS.index(edit['layer'])
        at = 11 - y + x * 12
        index = layer * 240 + at
        if index in touched or cells[index] != before or before == after or after not in ALLOWED[layer]:
            raise ValueError('An edit is duplicated, unchanged, has the wrong from value, or an invalid kind')
        if x in (0, 19) or y in (0, 11):
            raise ValueError('Keep the existing outer border exactly as supplied')
        touched.add(index)
        coordinates.add(at)
        updated[index] = after
    limit = 12 if repair else 180 if mode != 'modify' else 40
    if len(coordinates) > limit:
        raise ValueError(f'GLM changed too much of the layout; use at most {limit} board coordinates')
    if updated[:240].count(10) != 1 or updated[:240].count(7) != 1:
        raise ValueError('The level needs exactly one player and one home')
    if mode != 'redesign' and Counter(updated[:240]) != Counter(cells[:240]):
        raise ValueError('Keep the exact inventory of existing puzzle pieces, including their colors')
    for kind in (() if mode == 'redesign' else (10, 7)):
        if updated.index(kind) != cells.index(kind):
            raise ValueError('Keep the player and home in their existing cells')
    if not repair and mode == 'modify' and Counter(updated[240:480]) != Counter(cells[240:480]):
        raise ValueError('Keep the exact terrain inventory; move existing tiles rather than adding or removing them')
    if repair:
        structure = WALLS | {0, 77, 78, *range(99, 104)}
        before = Counter(kind for kind in cells[240:480] if kind not in structure)
        after = Counter(kind for kind in updated[240:480] if kind not in structure)
        if before != after:
            raise ValueError('Keep all pits, water, abyss, pressure walls and other terrain mechanics')
        if Counter(updated[480:]) != Counter(cells[480:]):
            raise ValueError('Keep the existing decoration inventory; move a blocker rather than deleting it')
    if mode == 'prettify':
        floors = {0, 60, 61, 77, 78, *range(99, 104)}
        walls = {12, 95, 96, 97, 98}
        for index in touched:
            before, after = cells[index], updated[index]
            if index < 240:
                raise ValueError('Prettify keeps every object and puzzle piece in place')
            if index < 480 and not any(before in group and after in group for group in (floors, walls)):
                raise ValueError('Prettify keeps mossy walls, buttons and all terrain mechanics unchanged')
            if index >= 480 and not (before in {0, 57, 58, 59} and after in {0, 57, 58, 59}):
                raise ValueError('Prettify only adds non-blocking decoration; keep trees, lanterns and boulders unchanged')
    if mode == 'redesign' and not partial and (len(coordinates) < 12 or not any(i < 240 for i in touched)):
        raise ValueError('Redesign a new puzzle layout and piece arrangement, not just its scenery')
    if mode != 'prettify' and not partial and not any(cells[i] != updated[i] and (cells[i] not in COSMETIC or updated[i] not in COSMETIC) for i in touched):
        raise ValueError('Change the push puzzle, not just its scenery or floor colors')
    for at in coordinates:
        kind, tile, decoration = updated[at], updated[240 + at], updated[480 + at]
        if 89 <= kind <= 91:
            if tile != 64:
                raise ValueError('Fish must remain on water')
        elif kind and kind != 71 and kind != tile and tile in WALLS | MOSS_WALLS | {64, 65} and not (kind in DOORS and tile in WALLS | MOSS_WALLS):
            raise ValueError('A puzzle piece overlaps blocked terrain')
        if decoration in BLOCKING_DECORATIONS and (kind or tile in WALLS | MOSS_WALLS | {64, 65}):
            raise ValueError('Keep trees clear of puzzle pieces and blocked terrain')
    return ''.join(f'{kind:02x}' for kind in updated)


def prove_proposal(number, candidate, proposed_route='', source_route='', seconds=30, prefixes=()):
    # A model's claim is never proof: replay the route in the shipped engine.
    for route in (proposed_route, source_route):
        if verify_route(number, candidate, route):
            return route
    references = [reference for reference in dict.fromkeys(prefixes)
                  if isinstance(reference, str) and re.fullmatch('[0123ft]{1,60000}', reference)]
    for reference in references[:3]:
        for length in dict.fromkeys((len(reference), max(1, len(reference) - 16), max(1, len(reference) // 2))):
            continued = subprocess.run([str(SOLVER), 'solve', '--level', str(number),
                '--seconds', '3', '--max-states', '500000', '--max-mb', '256', '--repair', reference[:length], candidate],
                cwd=ROOT, capture_output=True, text=True, timeout=13)
            route = continued.stdout.strip().splitlines()[0] if continued.stdout.strip() else ''
            if continued.returncode == 0 and verify_route(number, candidate, route):
                return route
    solved = subprocess.run([str(SOLVER), 'solve', '--level', str(number),
                             '--seconds', str(seconds), '--max-states', '5000000', '--max-mb', '768', candidate],
                            cwd=ROOT, capture_output=True, text=True, timeout=seconds + 10)
    route = solved.stdout.strip().splitlines()[0] if solved.stdout.strip() else ''
    if solved.returncode or not verify_route(number, candidate, route):
        raise ValueError('No winning route was proven. Keep the original puzzle structure and fix the pushes; do not remove goals or pieces')
    return route


DIFFICULTY = ('found by a quick plain search', 'found by the goal-chain search', 'not found by a 10-second search')


def difficulty(number, board, known_route=''):
    """How hard the solver finds a board: tier 0 when a quick plain search wins,
    1 when the goal-chain search does, 2 beyond a short search; with the length
    of the win. None when no win is known at all."""
    path = DRAFTS / 'difficulty.json'
    try:
        cache = json.loads(path.read_text())
    except (OSError, ValueError):
        cache = {}
    fingerprint = SOLVER.with_name('fingerprint').read_text() if SOLVER.with_name('fingerprint').exists() else str(SOLVER.stat().st_mtime_ns)
    key = hashlib.sha256(('push-effort-v3\n' + fingerprint + '\n' + board).encode()).hexdigest()
    if key in cache:
        return cache[key]

    def search(*options):
        result = subprocess.run([str(SOLVER), 'solve', '--level', str(number), *options, board],
                                cwd=ROOT, capture_output=True, text=True, timeout=40)
        route = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ''
        return route if result.returncode == 0 and verify_route(number, board, route) else ''
    route, tier = search('--only', 'bfs', '--seconds', '3', '--max-states', '300000', '--max-mb', '256'), 0
    if not route:
        route, tier = search('--seconds', '10', '--max-states', '3000000', '--max-mb', '512'), 1
    if not route:
        if not verify_route(number, board, known_route):
            return None
        route, tier = known_route, 2
    wins = []
    for candidate in dict.fromkeys((route, known_route)):
        if not candidate:
            continue
        replay = subprocess.run([str(SOLVER), 'analyze', '--level', str(number), board, candidate],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        if replay.returncode == 0:
            wins.append(dict(json.loads(replay.stdout), solution=candidate))
    if not wins:
        raise ValueError('The difficulty route did not pass the game engine')
    measured = dict(min(wins, key=lambda win: (win['pushes'], win['moves'])), tier=tier)
    cache[key] = measured
    atomic(path, json.dumps(dict(list(cache.items())[-200:])) + '\n')
    return measured


FEATURES = ('one-way passage', 'portal', 'trail', 'gate passage', 'lever', 'paint', 'pressure button', 'ice')
PIECES = {0: 'player move', 1: 'red ball', 2: 'blue ball', 3: 'green ball', 9: 'crate',
          44: 'cyan ball', 45: 'purple ball', 46: 'yellow ball'}


def mechanic_name(kind):
    if kind in (4, 5, 6, 47, 48, 49):
        return PIECES[{4: 1, 5: 2, 6: 3, 47: 44, 48: 45, 49: 46}[kind]].replace('ball', 'pit')
    if kind in (15, 16, 17, 50, 51, 52):
        return PIECES[{15: 1, 16: 2, 17: 3, 50: 44, 51: 45, 52: 46}[kind]].replace('ball', 'single-use paint')
    if kind == 13 or kind in range(131, 135): return 'pressure button (held by an object)'
    if kind in MOSS_WALLS: return 'pressure wall (open while its matching button is held)'
    if kind == 18: return 'crate goal'
    return 'floor or other terrain'


def analyze_route(number, board, route):
    replay = subprocess.run([str(SOLVER), 'explain', '--level', str(number), board, route],
                            cwd=ROOT, capture_output=True, text=True, timeout=10)
    if replay.returncode:
        raise ValueError('The source winning route could not be replayed; your level was kept')
    analysis = json.loads(replay.stdout)
    for event in analysis['events']:
        event['piece_name'] = PIECES.get(event['piece'], f"piece kind {event['piece']}")
        event['target_name'] = mechanic_name(event['target']) if event['piece'] else None
        event['used_mechanics'] = [name for bit, name in enumerate(FEATURES) if event['features'] & (1 << bit)]
    analysis['used_mechanics'] = [name for bit, name in enumerate(FEATURES)
                                  if analysis['used_features'] & (1 << bit)]
    analysis['coordinates'] = 'Landscape: x 0–19 left to right, y 0–11 top to bottom; actions 0 down, 1 left, 2 up, 3 right.'
    analysis['interpretation'] = ('Events are observed engine actions in a verified win, not proof that every action is necessary. '
                                  'Use their order and piece_id to identify staging, reuse and dependencies; ignore empty walking.')
    analysis['rules'] = ('Balls disappear in matching reusable pits. Paint recolors one ball once and is consumed permanently. '
                          'Crates cannot enter paint or pits and never change color. An object holds a pressure button; '
                          'its matching wall stays open only while a matching button is held. A lever toggles gates; '
                          'a pressure button does not toggle them. Kind 11 grants a permanent trail: subsequent player steps on '
                          'plain floor 0 leave trail 11, which blocks pushed objects but allows the player. Colored/material floors '
                          'do not grow trail, so replacing plain floor changes this mechanic. Remove every ball, collect apples '
                          'and fill crate goals, then enter home.')
    return analysis


def puzzle_shape(board, flip=0):
    """Mechanics and geometry, ignoring scenery, material palettes and ball colors."""
    values = [int(board[i:i + 2], 16) for i in range(0, 1440, 2)]
    shape = []
    for y in range(1, 19):
        for x in range(1, 11):
            at = (19 - y if flip & 2 else y) * 12 + (11 - x if flip & 1 else x)
            kind, tile, decor = (values[layer * 240 + at] for layer in range(3))
            if decor in BLOCKING_DECORATIONS or tile in WALLS:
                kind = 12
            elif kind == 0 or kind == tile:
                kind = tile
            if kind in COSMETIC or kind in (59, 60, 61): kind = 0
            elif kind in WALLS: kind = 12
            elif kind in MOSS_WALLS: kind = 14
            elif kind in (1, 2, 3, 44, 45, 46): kind = 1
            elif kind in (4, 5, 6, 47, 48, 49): kind = 4
            elif kind in (15, 16, 17, 50, 51, 52): kind = 15
            elif kind in range(131, 135): kind = 13
            elif kind in range(73, 76) or kind in range(85, 88): kind = 8
            elif kind in (92, 107, 110, 113): kind = 92
            elif kind in range(123, 127): kind = 123
            elif kind in (93, 108, 111, 114): kind = 93
            elif kind in (94, 109, 112, 115): kind = 94
            elif kind in (104, 116, 118, 120): kind = 104
            elif kind in (105, 117, 119, 121): kind = 105
            elif kind in range(66, 70):
                direction = kind - 66
                if flip & 1 and direction in (0, 2): direction = 2 - direction
                if flip & 2 and direction in (1, 3): direction = 4 - direction
                kind = 66 + direction
            shape.append(kind)
    return shape


def redesign_difference(candidate, reference):
    shape = puzzle_shape(candidate)
    return min(sum(a != b for a, b in zip(shape, puzzle_shape(reference, flip))) for flip in range(4))


def redesign_context(number, original, target):
    route = target.get('solution') if target else ''
    route = route or existing_route(number, original)
    if not route:
        route = prove_proposal(number, original, prefixes=learned_routes(number, original))
        target = difficulty(number, original, route)
    if not target:
        raise ValueError('Check the source puzzle before redesigning it')
    route = target.get('solution', route)
    source = analyze_route(number, original, route)
    previous, previous_board = None, None
    levels = json.loads((ROOT / 'levels/classic.json').read_text())['levels']
    level = next((item for item in levels if item['number'] == number - 1), None)
    if level:
        previous_board = board_hex(level)
        previous_route = existing_route(number - 1, previous_board)
        if previous_route:
            observed = analyze_route(number - 1, previous_board, previous_route)
            previous = dict(level=number - 1,
                metrics={key: observed[key] for key in ('moves', 'pushes', 'goals', 'mechanics')},
                used_mechanics=observed['used_mechanics'],
                milestones=[event for event in observed['events'] if event['features'] or not event['piece']][:20],
                materials=dict(Counter(str(int(previous_board[i:i + 2], 16)) for i in range(480, 960, 2))),
                meaning='Context for pacing and visual contrast, not a template to copy or a separate difficulty target.')
        else:
            previous = dict(level=number - 1, verified=False,
                            meaning='No verified winning route is available; do not infer its strategy.')
    return dict(source=source, previous_level=previous, previous_board=previous_board, target=target)


def glm_json(instruction, context, max_tokens, feedback='', timeout=120):
    base, key, model = glm_settings()
    messages = [dict(role='system', content=instruction), dict(role='user', content=json.dumps(context))]
    if feedback:
        messages.append(dict(role='user', content='The previous proposal failed validation. Correct it relative to the supplied grids: ' + feedback))
    payload = dict(model=model, temperature=0.5, max_tokens=max_tokens,
                   thinking={'type': 'disabled'}, response_format={'type': 'json_object'}, messages=messages)
    # GLM-5.3 always reasons. Asking to disable it leaves Coding Plan calls
    # reasoning at their default depth, often exhausting a JSON-sized budget.
    # https://docs.z.ai/guides/capabilities/thinking
    if 'glm-5.3' in model.lower():
        payload.update(thinking={'type': 'enabled'}, reasoning_effort='low', max_tokens=max_tokens + 2048)
    req = urllib.request.Request(base + '/chat/completions', data=json.dumps(payload).encode(),
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        result = json.load(response)
    choice = result['choices'][0]
    atomic(DRAFTS / 'glm-provider-last.json', json.dumps(dict(model=model,
        finish_reason=choice.get('finish_reason'), usage=result.get('usage', {}))) + '\n')
    content = (choice['message'].get('content') or '').strip()
    if choice.get('finish_reason') == 'length':
        raise ValueError('GLM exhausted its response budget; return a smaller step with concise edits')
    if not content:
        raise ValueError('GLM returned no JSON; your level was kept')
    return json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', content)), model


def plan_redesign(number, context):
    plan, _ = glm_json(
        'Analyze the engine-verified winning route BEFORE designing a new Shovey puzzle. '
        'Return only JSON with win_route_analysis (short text), complexity_changes (list of concrete push dependencies), '
        'theme (short visual art direction) and previous_level_difference (short text). Do not output grids yet. '
        'Explain the actual order of pushes, paint consumption, crate staging and button/gate reuse in the replay. '
        'Do not claim that an observed action is necessary without evidence. Plan a more complex compact puzzle, '
        'preserving at least the source objective, push and used-mechanic counts. Add interacting decisions, not walking or push loops. '
        'Use the previous level only for progression and contrast; choose a different structure and coherent material/scenery palette. '
        'This redesign is for the supplied level number, not the next one. Follow the supplied engine rules and labeled events: '
        'piece_id tracks the same object even after a BALL changes color; crates never change color and paint never renews. '
        'Use existing art only: stone, slate, brick, sandstone or timber walls and matching floors, grass, sand, '
        'flowers, grass tufts, mushrooms, fallen leaves or bluebells. Decoration must frame the puzzle and keep routes legible. '
        'No autonomous animals or invented art assets.',
        dict(level=number, source_route_analysis=context['source'], previous_level=context['previous_level']), 1400, timeout=60)
    if (not isinstance(plan, dict) or any(not isinstance(plan.get(key), str) or not plan[key].strip()
            for key in ('win_route_analysis', 'theme', 'previous_level_difference')) or
            not isinstance(plan.get('complexity_changes'), list) or not plan['complexity_changes'] or
            any(not isinstance(change, str) or not change.strip() for change in plan['complexity_changes'])):
        raise ValueError('GLM did not return a complete redesign plan; your level was kept')
    atomic(DRAFTS / f'{number:03}.glm-plan.json', json.dumps(plan, indent=2) + '\n')
    return plan


def check_redesign(original, candidate, context, measured):
    reason = too_easy(context['target'], measured)
    if reason:
        raise ValueError(reason)
    source = context['target']
    if not (measured['goals'] > source['goals'] or measured['mechanics'] > source['mechanics'] or
            measured['pushes'] >= source['pushes'] + max(2, (source['pushes'] + 9) // 10)):
        raise ValueError('Too easy: redesign needs a new objective, an actually used mechanic, or at least 10% more verified pushes')
    for label, reference in (('source', original), ('previous level', context['previous_board'])):
        if reference and redesign_difference(candidate, reference) < 12:
            raise ValueError(f'Redesign repeats the {label}; change the puzzle geometry and piece arrangement, not just colors or scenery')
    values = [int(candidate[i:i + 2], 16) for i in range(0, 1440, 2)]
    floors = {0, 60, 61, 77, 78, *range(99, 104)}
    if sum(values[at] == 0 and values[240 + at] in floors and values[480 + at] in {57, 58, 59, 135, 136, 137}
           for at in range(240)) < 3:
        raise ValueError('Redesign needs coherent non-blocking scenery on at least three clear floor cells')


def landscape_grids(board):
    values = [int(board[i:i + 2], 16) for i in range(0, 1440, 2)]
    return {name: [[values[layer * 240 + 11 - y + x * 12] for x in range(20)] for y in range(12)]
            for layer, name in enumerate(LAYERS)}


def guided_redesign(number, original, design, instruction, context, feedback=''):
    """Teach one bounded change at a time, retaining only engine-proven steps."""
    if 'work' not in design:
        # Legacy boards repeat floor kinds in cells. Give GLM clean layers;
        # this changes no behavior and is checked with the same winning route.
        values = [int(original[i:i + 2], 16) for i in range(0, 1440, 2)]
        for at in range(240):
            if values[at] == values[240 + at]: values[at] = 0
        clean = ''.join(f'{kind:02x}' for kind in values)
        route = design['target'].get('solution', '') or existing_route(number, original)
        if not verify_route(number, clean, route):
            raise ValueError('The source layers could not be normalized; your level was kept')
        design['work'] = dict(board=clean, route=route, steps=[], deadline=time.monotonic() + 360)
    work = design['work']
    stages = (
        ('strategy', 'Add a concrete push dependency from the redesign plan: staging a piece to unlock another task, '
                     'a scarce paint decision, or a crate objective behind a controlled passage. Preserve existing challenges. '
                     'Make the whole puzzle more complex; a loose apple or an unrelated push in open space is not a dependency.'),
        ('structure', 'Shape compact connected rooms and working lanes around the verified push sequence. '
                      'Use purposeful walls to remove unused open walking space and make the new dependency matter. '
                      'Create a recognizably different layout from the source and preceding level; colors alone do not count.'),
        ('decoration', 'Dress the verified puzzle in the planned visual theme. Keep every object and terrain mechanic fixed. '
                       'Only change ordinary wall/floor appearances and non-blocking decoration. Use at least three clear floor cells '
                       'for flowers, grass tufts, mushrooms, leaves or bluebells. Frame the rooms and leave objectives legible.'),
    )
    # A complete valid response may finish early; otherwise small steps teach
    # GLM with actual engine feedback and avoid giant unverified grid replies.
    start = len(work['steps'])
    pending = stages[start:] if start < len(stages) else (
        ('refine', 'Correct the rejected final check by strengthening the strategy or geometry. Keep the coherent scenery. '
                   'Do not inflate the route with walking or reversible push loops.'),)
    for stage, lesson in pending:
        remaining = work['deadline'] - time.monotonic()
        if remaining < 25:
            raise ValueError('Redesign took too long; your level was kept')
        atomic(DRAFTS / f'{number:03}.glm-status', dict(strategy='Building push sequence…',
            structure='Shaping rooms…', decoration='Adding scenery…', refine='Refining puzzle…')[stage])
        step_context = dict(context, **landscape_grids(work['board']), step=stage,
            existing_solution=work['route'], current_route_analysis=analyze_route(number, work['board'], work['route']),
            completed_steps=work['steps'], remaining_quality_issue=work.get('quality_feedback'))
        proposal, model = glm_json(instruction +
            '\nWork step by step on the CURRENT supplied grids. This step: ' + lesson +
            '\nFor this step OVERRIDE the full-grid output instruction: return only compact JSON '
            '{"edits":[{"layer":"cells|tiles|decorations","x":0,"y":0,"from":0,"to":0}],'
            '"solution":"...","explanation":"..."}. Use at most 32 explicit layer edits, not full grids. '
            'Each from must match the CURRENT grids. Keep the complete existing winning strategy where possible. '
            'If it needs to change, give the adjusted complete route; the engine will check and search it. '
            'Do not guess at rules. The next step receives the verified result and feedback.',
            step_context, 2200, feedback, timeout=min(60, max(10, int(remaining - 20))))
        if isinstance(proposal, dict) and 'edits' not in proposal:
            # Full-board responses from older providers still pass through
            # every normal final check, relative to the original board.
            return proposal, model
        try:
            candidate = apply_proposal(work['board'], proposal, mode='redesign', partial=True)
            if stage == 'decoration':
                before = [int(work['board'][i:i + 2], 16) for i in range(0, 1440, 2)]
                after = [int(candidate[i:i + 2], 16) for i in range(0, 1440, 2)]
                for at, (old, new) in enumerate(zip(before, after)):
                    if old == new: continue
                    if at in range(240, 480) and 11 in before[:480] and (old == 0) != (new == 0):
                        raise ValueError('Keep plain floor unchanged around a trail puzzle; material floors alter its pushing rules')
                    if at < 240 or (at < 480 and not any(old in group and new in group
                            for group in ({0, 60, 61, 77, 78, *range(99, 104)}, {12, 95, 96, 97, 98}))) or (
                            at >= 480 and not (old in {0, 57, 58, 59, 135, 136, 137} and new in {0, 57, 58, 59, 135, 136, 137})):
                        raise ValueError('The decoration step changed puzzle mechanics; keep all objects and mechanics fixed')
            route = prove_proposal(number, candidate, proposal.get('solution', ''), work['route'], seconds=15,
                                   prefixes=[work['route']])
        except ValueError as error:
            error.proposal = proposal
            raise
        work.update(board=candidate, route=route)
        work['steps'].append(dict(stage=stage, explanation=str(proposal.get('explanation', ''))[:1000]))
        atomic(DRAFTS / f'{number:03}.glm-teaching.json', json.dumps(dict(
            source=original, board=candidate, solution=route, steps=work['steps']), indent=2) + '\n')
        # Measure the best win found, so a padded model route earns nothing.
        measured = difficulty(number, candidate, route)
        try:
            check_redesign(original, candidate, design, measured)
        except ValueError as error:
            work['quality_feedback'] = str(error)
            continue
        return dict(landscape_grids(candidate), solution=route,
                    explanation=' '.join(step['explanation'] for step in work['steps'])), model
    # Return the whole assembled proposal to the normal final validation. A
    # rejected final check is fed back into a refinement step on the next try.
    return dict(landscape_grids(work['board']), solution=work['route'],
                explanation=' '.join(step['explanation'] for step in work['steps'])), model


def too_easy(target, measured):
    """Why a proposal is easier than its source level, or an empty string."""
    for name in ('goals', 'pushes', 'mechanics'):
        if measured.get(name, 0) < target.get(name, 0):
            return (f"Too easy: the checked win needs {measured.get(name, 0)} {name}; the source needs "
                    f"{target[name]}. Keep at least as many required objectives and purposeful pushes. "
                    'A long walking route or repeated moves does not make the push puzzle harder.')
    if 'pushes' in target and 'goals' in target:
        # Search speed depends on the heuristic and machine. Finding a hard
        # puzzle quickly is useful, and does not make its strategy trivial.
        return ''
    if measured['tier'] > target['tier'] or (measured['tier'] == target['tier'] and
                                             (target['tier'] == 2 or measured['moves'] >= 0.7 * target['moves'])):
        return ''
    return (f"Too easy: the solver's win was {DIFFICULTY[measured['tier']]} in {measured['moves']} moves, but the "
            f"original's was {DIFFICULTY[target['tier']]} in {target['moves']} moves. Make it at least as hard: several "
            'objectives whose pushes depend on each other, pieces that must be moved aside in the right order, tight rooms '
            'where a careless push deadlocks, and lever, gate or button sequences. Long empty walks are not difficulty.')


def proven_variations(number, original, route, limit=8):
    """Keep inventory and nearby geometry, proving every candidate's route."""
    if not route:
        return []
    layers = [[int(original[i:i + 2], 16) for i in range(start, start + 480, 2)]
              for start in (0, 480, 960)]
    cells, tiles, decorations = layers
    pushable = {1, 2, 3, 9, 36, 37, 38, 44, 45, 46, 53, 54, 55}
    goals = [at for at in range(240) if cells[at] in {18, 39} or tiles[at] in {4, 5, 6, 47, 48, 49}]

    def distance(a, b):
        return abs(a % 12 - b % 12) + abs(a // 12 - b // 12)

    def edit(layer, at, before, after):
        return dict(layer=layer, x=at // 12, y=11 - at % 12, **{'from': before, 'to': after})

    interior = [at for at in range(240) if 0 < at % 12 < 11 and 0 < at // 12 < 19]
    empty = [at for at in interior if cells[at] == 0 and tiles[at] in {0, 77, 78, *range(99, 104)} and decorations[at] not in BLOCKING_DECORATIONS]
    proposals = []
    for source in interior:
        kind = cells[source]
        if kind in pushable:
            for target in empty:
                if not 1 <= distance(source, target) <= 2:
                    continue
                # A longer approach to a goal gives GLM a useful alternative
                # to shortening a push or merely changing scenery.
                farther = bool(goals) and min(distance(target, goal) for goal in goals) > min(distance(source, goal) for goal in goals)
                score = 20 + 8 * farther - distance(source, target)
                proposals.append((score, [edit('cells', source, kind, 0), edit('cells', target, 0, kind)]))
        elif kind == 0 and tiles[source] in WALLS and decorations[source] == 0:
            for target in empty:
                if distance(source, target) != 1 or decorations[target] != 0:
                    continue
                nearby = sum(distance(target, at) <= 2 for at in interior if cells[at] in pushable | {13, 18, 39, 93})
                proposals.append((5 + nearby, [edit('tiles', source, tiles[source], tiles[target]),
                                             edit('tiles', target, tiles[target], tiles[source])]))
    verified = []
    alternatives = []
    seen = set()
    for _, edits in sorted(proposals, key=lambda item: item[0], reverse=True)[:160]:
        proposal = dict(edits=edits, solution=route)
        try:
            candidate = apply_proposal(original, proposal)
        except ValueError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if verify_route(number, candidate, route):
            verified.append(proposal)
            if len(verified) == limit:
                break
        elif len(alternatives) < 3:
            alternatives.append((proposal, candidate))
    # A single nudge that leaves the entire old route unchanged is rarely a
    # useful redesign. Combine independently valid edits and replay the whole
    # result, rather than offering GLM eight versions of the same tiny move.
    combined = []
    for left in range(len(verified)):
        for right in range(left + 1, len(verified)):
            proposal = dict(edits=verified[left]['edits'] + verified[right]['edits'], solution=route)
            try:
                candidate = apply_proposal(original, proposal)
            except ValueError:
                continue
            if verify_route(number, candidate, route):
                combined.append(proposal)
                if len(combined) == limit:
                    return combined
    # When independent moves cannot be combined, prove a genuinely new route
    # for a nearby change instead of falling back to the old one-square nudge.
    if not combined:
        for proposal, candidate in alternatives:
            try:
                solved = subprocess.run([str(SOLVER), 'solve', '--level', str(number),
                    '--seconds', '3', '--max-states', '250000', '--max-mb', '128', candidate],
                    cwd=ROOT, capture_output=True, text=True, timeout=5)
            except subprocess.TimeoutExpired:
                continue
            solution = solved.stdout.strip().splitlines()[0] if solved.stdout.strip() else ''
            if solved.returncode == 0 and verify_route(number, candidate, solution):
                combined.append(dict(proposal, solution=solution))
    return combined[:limit]


def modify_once(number, feedback='', choices=None, repair=False, mode='modify', target=None, design=None):
    status = DRAFTS / f'{number:03}.glm-status'
    atomic(status, 'Repairing…' if repair else 'Prettifying…' if mode == 'prettify' else 'Designing…')
    original = (DRAFTS / f'{number:03}.glm-base').read_text().strip()
    if not re.fullmatch('[0-9a-f]{1440}', original):
        raise ValueError('The source board is incomplete; your level was kept')
    cells = [int(original[i:i + 2], 16) for i in range(0, 1440, 2)]
    rows = [[cells[(11 - y) + x * 12 + layer * 240] for x in range(20)] for layer in range(3) for y in range(12)]
    source_route = existing_route(number, original)
    if not repair and mode == 'redesign' and design is None:
        atomic(status, 'Analyzing winning route…')
        design = redesign_context(number, original, target)
        target = design['target']
        atomic(status, 'Planning redesign…')
        design['plan'] = plan_redesign(number, design)
    choices = choices or []
    task = (
        'You repair Shovey push puzzles. Make the supplied EXISTING board winnable with the smallest necessary edits. '
        'Find the deadlock or blocked route, think through the required pushes, and propose a complete winning route. '
        'Preserve the recognizable rooms and puzzle, its player and home positions, and the exact inventory and colors of all objects. '
        'Keep every goal, colored pit, portal, paint, lever, gate, pressure wall, water and abyss. Never remove an objective to claim a win. '
        'You may open or adjust a few ordinary walls and floor cells to provide access or pushing room, or reposition existing pieces. '
        'You may move a blocking tree, lantern or boulder, preserving the exact decoration inventory. '
        'Change at most 12 board coordinates; prefer the fewest changes that resolve the actual problem. Do not redesign the level. '
    ) if repair else (
        'You design Shovey push puzzles. Improve the supplied EXISTING level with a small purposeful variation inspired by its current solution and mechanics. '
        'Think through the pushes and a winning route; use compact connected rooms and purposeful obstacles, not empty walking or random decoration. '
        'This is a variation of THIS puzzle, not a new unrelated puzzle. Preserve the exact inventory of every non-empty object kind, '
        'every colored pit, all portal pairs, paints, gates, plates and levers. Keep the player and home in their existing cells. '
        'Keep a similar strategic winning route and dependencies but give them a different purposeful layout; change at most 40 board coordinates. '
        'Reposition a few selected crates, balls or walls to create one interesting dependency or push sequence. Prefer 2–12 changed coordinates. '
        'Design the variation yourself. Avoid merely nudging one unused piece while the old solution works unchanged. '
        'If the old route still wins, change at least four coordinates with a concrete purpose in the push puzzle. '
        'Do not add goals, new mechanics, new items or extra scenery. Keep comparable difficulty. '
    )
    if not repair and mode == 'redesign':
        task = (
            'Design a completely NEW Shovey level in this board, with a new layout, piece arrangement and winning strategy. '
            'The supplied board is context, not a layout to preserve. You may change inventory and move the player and home. '
            'Use compact connected rooms, purposeful pushes and at least one real puzzle objective. '
            'Follow the supplied redesign_plan, derived from source_route_analysis, and make the strategy more complex. '
            'Use previous_level_context for pacing and contrast, not as a layout to copy. '
            'Create a unique visual identity with a coherent floor/wall palette and at least three non-blocking scenery cells. '
            'Keep the working spaces legible; decorate room edges and alcoves without covering puzzle pieces. '
            'Think through a complete winning route. Keep exactly one player and one home and the existing outer border. '
            'Do not add autonomous animals. Do not merely recolor or slightly nudge the old puzzle. '
        )
    elif not repair and mode == 'prettify':
        task = (
            'Make this exact Shovey puzzle prettier with a coherent floor and wall palette and more non-blocking decoration. '
            'Preserve its strategy, every object position, player, home and ALL mechanics. Do not edit the cells layer. '
            'Only swap ordinary floor IDs within 0/60/61/77/78/99/100/101/102/103, ordinary wall IDs within 12/95/96/97/98, '
            'and add or adjust decorations 0/57/58/59 (empty, flowers, grass, small scenery). '
            'NEVER add, remove, recolor or move any mossy wall or pressure button: their matching color controls puzzle logic. '
            'Keep pits, paint, ice, water, abyss, portals, gates, levers and blocking trees/lanterns/boulders exactly unchanged. '
            'Keep the outer border. The existing winning route must still win. '
        )
    instruction = (task +
        ('Return only JSON with keys cells, tiles, decorations, solution, explanation. ' if mode == 'redesign' else
         'Return only JSON with keys edits, solution, explanation. Do NOT regenerate the grids. ')
        + 'For edit responses, edits is a list of {"layer":"cells","x":integer,"y":integer,"from":old ID,"to":new ID} objects. '
        'layer may be cells, tiles' + (' or decorations. ' if repair or mode != 'modify' else '. ') +
        'Coordinates use the supplied LANDSCAPE grids: x is column 0–19 from left, y is row 0–11 from top. '
        'Every from value must match the input. Give each layer coordinate once. Move pieces by clearing the old cell and filling the new cell. ' +
        ('Preserve every object and decoration count; only ordinary walls and floor counts may change. Keep the outer border. ' if repair else
         'Preserve the exact count of EVERY kind in EACH layer, including empty cells, walls and floor types. Do not edit decorations or the outer border. ' if mode == 'modify' else
         'Follow the mode-specific editing restrictions above. ') +
        'explanation briefly describes the concrete gameplay improvement. solution is a winning action string, not a claim of solvability. '
        'In this LANDSCAPE view route digits mean 0=DOWN, 1=LEFT, 2=UP, 3=RIGHT, f=fire, t=advance time. '
        'Cells: 0 empty, 1/2/3 red/blue/green balls, 7 home, 8 paired teleporters, 9 crate, 10 player (exactly one), '
        '13 green pressure button, 14 mossy stone wall (opens while an object holds a green button), '
        '127/128/129/130 mossy slate/brick/sandstone/timber walls, opened only by their matching 131/132/133/134 blue/red/yellow/purple buttons. '
        '104/105 wooden door closed/open and 116/117,118/119,120/121 red/blue/green doors: placed over the existing wall and opened by walking into them. '
        '15/16/17 paint red/blue/green, '
        '18 crate goal, 21 apple, 33 key, 34 lock, 44/45/46 cyan/purple/yellow balls, 50/51/52 matching paint, '
        '73/74/75/85/86/87 portals (paired by ID), 92 orange gate, 93/94 orange lever off/on, '
        '107 red gate with 108/109 red lever, 110 blue gate with 111/112 blue lever, 113 green gate with 114/115 green lever. '
        '123/124/125/126 orange/red/blue/green gates start OPEN and close when matching levers are on. Other gates start closed and open. '
        'Any matching lever toggles their shared state; all lever handles of that color switch together. '
        'Tiles: 0 paving, 12 wall, 14 mossy pressure wall, 4/5/6 red/blue/green pits, 47/48/49 cyan/purple/yellow pits, 64 water, '
        '65 abyss, 70 ice, 77 grass, 78 sand; 95/96/97/98 slate/brick/sandstone/timber walls; 99/100/101/102 matching floors, 103 mossy floor. '
        'Objects 82 duck, 83 turtle and 88 crab wander and block movement; 89/90/91 fish stay on water. '
        'Decorations: 0 empty, 57 flowers, 58 grass tuft, 135 mushrooms, 136 fallen leaves, 137 bluebells, 138 lily pads (on water), '
        '84 blocking tree, 106 blocking lantern, 122 blocking boulder, 139 blocking berry bush, 140 blocking flower pot, '
        '141 blocking barrel, 142 blocking tree stump. '
        'A ball pushed onto matching pit disappears; pit is reusable. Paint recolors a ball and is consumed. '
        'No object can enter or fill abyss: balls, crates, bombs and color blocks all stop at its edge. '
        'Player must remove ALL balls, collect every apple, cover all crate goals, then enter home. '
        'Crates with no goals can stay on the board. Objects cannot be pushed into portals, home, water or walls. '
        'Do not add animals or autonomous objects. Preserve the outer border exactly. No scripts, tools, commands, prose outside the JSON.')
    if target:
        instruction += ('difficulty_target is how hard the engine\'s solver finds the source level. Your level must be at least as '
                        'hard: keep at least its objective count, verified push count and number of actually used mechanics. '
                        'Search tier is diagnostic, not a difficulty requirement; faster search must not reject a strategically harder puzzle. '
                        'Long empty walks do not replace purposeful pushes or interacting objectives. Never make it easier; easier proposals are rejected. ')
    if mode == 'redesign':
        instruction += ('Instead of edits, return full cells, tiles and decorations grids, each 12 rows of 20 integer IDs in landscape order, '
                        'plus solution and explanation. Preserve the outer border from the input exactly.')
    if choices:
        instruction += (
            'The supplied verified_variations are small edits of this exact board, already proven to win in the real engine. '
            'Choose the one that most improves the push sequence, dependencies or use of space, inspired by the existing puzzle. '
            'Return only {"choice":zero-based integer,"explanation":"the concrete gameplay improvement"}. '
            'Do not reproduce grids, edits or the solution. The engine will apply and recheck the selected variation.')
    context = dict(
        level=number, cells=rows[:12], tiles=rows[12:24], decorations=rows[24:],
        existing_solution=source_route or None,
        difficulty_target=dict(target, meaning=DIFFICULTY[target['tier']]) if target else None,
        verified_variations=[dict(choice=index, edits=choice['edits']) for index, choice in enumerate(choices)])
    if design:
        context.update(source_route_analysis=design['source'], previous_level_context=design['previous_level'],
                       redesign_plan=design['plan'])
    if design:
        proposal, model = guided_redesign(number, original, design, instruction, context, feedback)
    else:
        proposal, model = glm_json(instruction, context,
            800 if choices else 6000 if mode == 'prettify' else 3500, feedback)
    if choices and isinstance(proposal, dict) and 'choice' in proposal:
        choice = proposal['choice']
        if type(choice) is not int or not 0 <= choice < len(choices):
            raise ValueError('Choose one of the supplied engine-proven variations')
        proposal = choices[choice] | {'explanation': str(proposal.get('explanation', ''))[:1000]}
    try:
        candidate = apply_proposal(original, proposal, repair=repair, mode=mode)
        changed = {at % 240 for at in range(720)
                   if original[at * 2:at * 2 + 2] != candidate[at * 2:at * 2 + 2]}
        if not repair and mode == 'modify' and len(changed) < 4 and verify_route(number, candidate, source_route):
            raise ValueError('Only one piece was nudged and the old route still wins unchanged. Design a fuller push variation or a change requiring a new route')
        atomic(status, 'Checking repair…' if repair else 'Checking variation…')
        if mode == 'prettify':
            if source_route and not verify_route(number, candidate, source_route):
                raise ValueError('Prettify changed the winning route; keep all mechanics unchanged')
            route = source_route
        else:
            route = prove_proposal(number, candidate, proposal.get('solution', ''), source_route if mode != 'redesign' else '')
            if target:
                atomic(status, 'Checking difficulty…')
                measured = difficulty(number, candidate, route)
                reason = too_easy(target, measured) if measured else 'The engine could not measure this proposal'
                if reason:
                    raise ValueError(reason)
                if design:
                    check_redesign(original, candidate, design, measured)
    except (ValueError, subprocess.TimeoutExpired) as error:
        rejected = ValueError(str(error) if isinstance(error, ValueError) else 'The route check ran out of time; simplify the variation')
        rejected.proposal = proposal
        raise rejected from error
    if route:
        atomic(DRAFTS / f'{number:03}.glm-proof', candidate + '\n' + route)
    else:
        (DRAFTS / f'{number:03}.glm-proof').unlink(missing_ok=True)
    atomic(DRAFTS / f'{number:03}.glm-explanation', str(proposal.get('explanation', ''))[:1000])
    atomic(DRAFTS / f'{number:03}.glm-result', candidate)
    atomic(DRAFTS / f'{number:03}.glm-details.json', json.dumps(dict(
        model=model, mode='repair' if repair else mode, changed_coordinates=len(changed), solution_length=len(route),
        **(dict(plan=design['plan'], source_route_analysis=design['source'],
                previous_level_context=design['previous_level'], measured=measured,
                teaching_steps=design.get('work', {}).get('steps', []),
                difference_from_source=redesign_difference(candidate, original),
                difference_from_previous=redesign_difference(candidate, design['previous_board']) if design['previous_board'] else None)
           if design else {}),
        explanation=str(proposal.get('explanation', ''))[:1000]), indent=2) + '\n')
    atomic(status, 'Repair ready' if repair else 'Variation ready')
    atomic(DRAFTS / f'{number:03}.glm-state', 'ready')


def modify(number, repair=False, mode='modify'):
    atomic(DRAFTS / f'{number:03}.glm-state', 'working')
    glm_settings()  # Configuration errors cannot be corrected by another proposal.
    feedback = ''
    target = None
    design = None
    if not repair and mode in ('modify', 'redesign'):
        source = (DRAFTS / f'{number:03}.glm-base').read_text().strip()
        if re.fullmatch('[0-9a-f]{1440}', source):
            atomic(DRAFTS / f'{number:03}.glm-status', 'Measuring difficulty…')
            target = difficulty(number, source, existing_route(number, source))
            if mode == 'redesign':
                atomic(DRAFTS / f'{number:03}.glm-status', 'Analyzing winning route…')
                design = redesign_context(number, source, target)
                target = design['target']
                atomic(DRAFTS / f'{number:03}.glm-status', 'Planning redesign…')
                design['plan'] = plan_redesign(number, design)
    started = time.monotonic()
    for attempt in range(3):
        try:
            choices = None
            if attempt == 2 and not repair and mode == 'modify':
                original = (DRAFTS / f'{number:03}.glm-base').read_text().strip()
                atomic(DRAFTS / f'{number:03}.glm-status', 'Finding proven alternatives…')
                choices = proven_variations(number, original, existing_route(number, original))
            modify_once(number, feedback, choices, repair=repair, mode=mode, target=target, design=design)
            return
        except ValueError as error:
            feedback = json.dumps(dict(reason=str(error), rejected_proposal=getattr(error, 'proposal', None)))
            atomic(DRAFTS / f'{number:03}.glm-details.json', json.dumps(dict(
                attempt=attempt + 1, seconds=round(time.monotonic() - started, 1),
                reason=str(error), rejected_proposal=getattr(error, 'proposal', None)), indent=2) + '\n')
    if feedback and json.loads(feedback)['reason'].startswith('Too easy'):
        raise ValueError('No variation as hard as the original was found. Try GLM again.')
    raise ValueError('No winnable repair found. Try Fix it again.' if repair else 'No solvable variation found. Try GLM again.')


def failure_message(error):
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return 'GLM access denied. Check the provider key.'
        if error.code == 429:
            return 'GLM limit reached. Try again shortly.'
        return f'GLM provider error ({error.code}). Try again.'
    if isinstance(error, (urllib.error.URLError, TimeoutError)):
        return 'GLM connection failed. Try again.'
    if isinstance(error, ValueError):
        return str(error)[:220]
    return 'GLM request failed. Try again.'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('approve', 'glm', 'glm-redesign', 'glm-prettify', 'fix', 'update', 'update-all'))
    parser.add_argument('level', type=int)
    args = parser.parse_args()
    if not 1 <= args.level <= (175 if args.action in ('update', 'update-all') else 174):
        parser.error('level is outside the editor')
    try:
        if args.action == 'update':
            update()
        elif args.action == 'update-all':
            update_all()
        elif args.action == 'fix':
            modify(args.level, repair=True)
        elif args.action.startswith('glm'):
            modify(args.level, mode={'glm': 'modify', 'glm-redesign': 'redesign', 'glm-prettify': 'prettify'}[args.action])
        else:
            approve(args.level)
    except Exception as error:
        message = failure_message(error) if args.action in ('glm', 'glm-redesign', 'glm-prettify', 'fix') else 'Update failed. Retry.'
        path = DRAFTS / (f'{args.level:03}.glm-status' if args.action in ('glm', 'glm-redesign', 'glm-prettify', 'fix') else 'publish-status')
        atomic(path, message[:220])
        if args.action in ('glm', 'glm-redesign', 'glm-prettify', 'fix'):
            atomic(DRAFTS / f'{args.level:03}.glm-state', 'error')
        raise SystemExit(1)
