#!/usr/bin/env python3
"""Developer editor actions. Model proposals stay drafts until exact approval."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import urllib.request
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / 'backup/editor-drafts'
SOLVER = ROOT / 'build/solver/shovey-solve-classic'
LAYERS = ('cells', 'tiles', 'decorations')
COSMETIC = {0, 57, 58, 59, 60, 61, 77, 78}
WALLS = {12, 62, 63, 76, 95, 96, 97, 98}
ALLOWED = (
    ({0, *range(1, 77), *range(82, 99)} - {22, 24, 32, 41, 42, 43}),
    {0, 4, 5, 6, 12, 14, 47, 48, 49, *range(57, 72), 76, 77, 78, *range(95, 99)},
    {0, 57, 58, 59, 84},
)


def atomic(path, text):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(text)
    temporary.replace(path)


def board_hex(level):
    cells = ''.join(level['cells'])
    defaults = []
    for i in range(0, 480, 2):
        kind = int(cells[i:i + 2], 16)
        tile = kind if kind in {0, 4, 5, 6, 12, 14, 47, 48, 49, 60, 61, 63, 64, 65, 70, 76, 77, 78, *range(95, 99)} else 77 if kind == 7 else 64 if 89 <= kind <= 91 else 12 if kind == 62 else 0
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
    atomic(DRAFTS / 'publish-status', 'Updating…')
    subprocess.Popen([sys.executable, str(ROOT / 'scripts/publish-approved.py')], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def update():
    # Updating an approved campaign never depends on the open draft's proof.
    atomic(DRAFTS / 'publish-status', 'Updating…')
    subprocess.Popen([sys.executable, str(ROOT / 'scripts/publish-approved.py'), '--force'], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


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
        raise ValueError('Harmony has no configured GLM key')
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


def apply_proposal(original, proposal):
    """Apply small, explicit landscape-coordinate edits to the supplied board."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get('edits'), list):
        raise ValueError('Return a JSON object with an edits list, not a replacement level')
    if not 1 <= len(proposal['edits']) <= 80:
        raise ValueError('Use between 1 and 80 layer edits at at most 40 board coordinates')
    cells = [int(original[i:i + 2], 16) for i in range(0, 1440, 2)]
    updated = cells.copy()
    touched = set()
    coordinates = set()
    for edit in proposal['edits']:
        if not isinstance(edit, dict) or edit.get('layer') not in LAYERS[:2]:
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
    if len(coordinates) > 40:
        raise ValueError('GLM changed too much of the layout; use at most 40 board coordinates')
    if cells[:240].count(10) != 1 or cells[:240].count(7) != 1:
        raise ValueError('The source level needs one player and one home')
    if Counter(updated[:240]) != Counter(cells[:240]):
        raise ValueError('Keep the exact inventory of existing puzzle pieces, including their colors')
    for kind in (10, 7):
        if updated.index(kind) != cells.index(kind):
            raise ValueError('Keep the player and home in their existing cells')
    if Counter(updated[240:480]) != Counter(cells[240:480]):
        raise ValueError('Keep the exact terrain inventory; move existing tiles rather than adding or removing them')
    if not any(cells[i] != updated[i] and (cells[i] not in COSMETIC or updated[i] not in COSMETIC) for i in touched):
        raise ValueError('Change the push puzzle, not just its scenery or floor colors')
    for at in coordinates:
        kind, tile, decoration = updated[at], updated[240 + at], updated[480 + at]
        if 89 <= kind <= 91:
            if tile != 64:
                raise ValueError('Fish must remain on water')
        elif kind and kind != 71 and kind != tile and tile in WALLS | {14, 64, 65}:
            raise ValueError('A puzzle piece overlaps blocked terrain')
        if decoration == 84 and (kind or tile in WALLS | {14, 64, 65}):
            raise ValueError('Keep trees clear of puzzle pieces and blocked terrain')
    return ''.join(f'{kind:02x}' for kind in updated)


def prove_proposal(number, candidate, proposed_route='', source_route=''):
    # A model's claim is never proof: replay the route in the shipped engine.
    for route in (proposed_route, source_route):
        if verify_route(number, candidate, route):
            return route
    solved = subprocess.run([str(SOLVER), 'solve', '--level', str(number),
                             '--seconds', '30', '--max-states', '5000000', '--max-mb', '768', candidate],
                            cwd=ROOT, capture_output=True, text=True, timeout=40)
    route = solved.stdout.strip().splitlines()[0] if solved.stdout.strip() else ''
    if solved.returncode or not verify_route(number, candidate, route):
        raise ValueError('No winning route was proven. Keep the original puzzle structure and fix the pushes; do not remove goals or pieces')
    return route


def proven_variations(number, original, route, limit=8):
    """Keep the current solution and inventory while moving nearby pieces or walls."""
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
    empty = [at for at in interior if cells[at] == 0 and tiles[at] in {0, 77, 78} and decorations[at] != 84]
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
    return verified


def modify_once(number, feedback=''):
    status = DRAFTS / f'{number:03}.glm-status'
    atomic(status, 'GLM is designing a variation…')
    original = (DRAFTS / f'{number:03}.glm-base').read_text().strip()
    if not re.fullmatch('[0-9a-f]{1440}', original):
        raise ValueError('The source board is incomplete; your level was kept')
    cells = [int(original[i:i + 2], 16) for i in range(0, 1440, 2)]
    rows = [[cells[(11 - y) + x * 12 + layer * 240] for x in range(20)] for layer in range(3) for y in range(12)]
    source_route = existing_route(number, original)
    choices = proven_variations(number, original, source_route)
    instruction = (
        'You design Shovey push puzzles. Improve the supplied EXISTING level with a small purposeful variation inspired by its current solution and mechanics. '
        'Think through the pushes and a winning route; use compact connected rooms and purposeful obstacles, not empty walking or random decoration. '
        'This is a variation of THIS puzzle, not a new unrelated puzzle. Preserve the exact inventory of every non-empty object kind, '
        'every colored pit, all portal pairs, paints, gates, plates and levers. Keep the player and home in their existing cells. '
        'Keep the main rooms and recognizable passage layout; change at most 40 board coordinates across the layers. '
        'Reposition a few selected crates, balls or walls to create one interesting dependency or push sequence. Prefer 2–12 changed coordinates. '
        'Do not add goals, new mechanics, new items or extra scenery. Keep comparable difficulty. '
        'Return only JSON with keys edits, solution, explanation. Do NOT regenerate the grids. '
        'edits is a list of {"layer":"cells" or "tiles","x":integer,"y":integer,"from":old ID,"to":new ID}. '
        'Coordinates use the supplied LANDSCAPE grids: x is column 0–19 from left, y is row 0–11 from top. '
        'Every from value must match the input. Give each layer coordinate once. Move pieces by clearing the old cell and filling the new cell. '
        'Preserve the exact count of EVERY kind in EACH layer, including empty cells, walls and floor types. Do not edit decorations or the outer border. '
        'explanation briefly describes the concrete gameplay improvement. solution is a winning action string, not a claim of solvability. '
        'In this LANDSCAPE view route digits mean 0=DOWN, 1=LEFT, 2=UP, 3=RIGHT, f=fire, t=advance time. '
        'Cells: 0 empty, 1/2/3 red/blue/green balls, 7 home, 8 paired teleporters, 9 crate, 10 player (exactly one), '
        '13 pressure plate, 14 mossy wall (opens while any object holds a plate), 15/16/17 paint red/blue/green, '
        '18 crate goal, 21 apple, 33 key, 34 lock, 44/45/46 cyan/purple/yellow balls, 50/51/52 matching paint, '
        '73/74/75/85/86/87 portals (paired by ID), 92 lever gate, 93 lever (pushing toggles all lever gates). '
        'Tiles: 0 paving, 12 wall, 14 mossy pressure wall, 4/5/6 red/blue/green pits, 47/48/49 cyan/purple/yellow pits, 64 water, '
        '65 abyss, 70 ice, 77 grass, 78 sand. Decorations: 0 empty, 57 flowers, 58 grass tuft, 59 pebbles, 84 blocking tree. '
        'A ball pushed onto matching pit disappears; pit is reusable. Paint recolors a ball and is consumed. '
        'Player must remove ALL balls, collect every apple, cover all crate goals, then enter home. '
        'Crates with no goals can stay on the board. Objects cannot be pushed into portals, home, water or walls. '
        'Do not add animals or autonomous objects. Keep outer border walled. No scripts, tools, commands, prose outside the JSON.')
    if choices:
        instruction += (
            'The supplied verified_variations are small edits of this exact board, already proven to win in the real engine. '
            'Choose the one that most improves the push sequence, dependencies or use of space, inspired by the existing puzzle. '
            'Return only {"choice":zero-based integer,"explanation":"the concrete gameplay improvement"}. '
            'Do not reproduce grids, edits or the solution. The engine will apply and recheck the selected variation.')
    base, key, model = glm_settings()
    messages = [dict(role='system', content=instruction), dict(role='user', content=json.dumps(dict(
        level=number, cells=rows[:12], tiles=rows[12:24], decorations=rows[24:],
        existing_solution=source_route or None,
        verified_variations=[dict(choice=index, edits=choice['edits']) for index, choice in enumerate(choices)])))]
    if feedback:
        messages.append(dict(role='user', content='The previous proposal failed validation. Correct it relative to the ORIGINAL grids: ' + feedback))
    payload = dict(model=model, temperature=0.5, max_tokens=800 if choices else 6000,
                   thinking={'type': 'disabled'}, response_format={'type': 'json_object'},
                   messages=messages)
    req = urllib.request.Request(base + '/chat/completions', data=json.dumps(payload).encode(),
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.load(response)
    content = result['choices'][0]['message']['content'].strip()
    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content)
    proposal = json.loads(content)
    if choices and isinstance(proposal, dict) and 'choice' in proposal:
        choice = proposal['choice']
        if type(choice) is not int or not 0 <= choice < len(choices):
            raise ValueError('Choose one of the supplied engine-proven variations')
        proposal = choices[choice] | {'explanation': str(proposal.get('explanation', ''))[:1000]}
    try:
        candidate = apply_proposal(original, proposal)
        atomic(status, 'GLM variation is being checked for a real winning route…')
        route = prove_proposal(number, candidate, proposal.get('solution', ''), source_route)
    except (ValueError, subprocess.TimeoutExpired) as error:
        rejected = ValueError(str(error) if isinstance(error, ValueError) else 'The route check ran out of time; simplify the variation')
        rejected.proposal = proposal
        raise rejected from error
    atomic(DRAFTS / f'{number:03}.glm-proof', candidate + '\n' + route)
    atomic(DRAFTS / f'{number:03}.glm-explanation', str(proposal.get('explanation', ''))[:1000])
    atomic(DRAFTS / f'{number:03}.glm-result', candidate)
    atomic(status, 'GLM variation ready, with an engine-proven winning route.')


def modify(number):
    feedback = ''
    for attempt in range(3):
        try:
            return modify_once(number, feedback)
        except ValueError as error:
            feedback = json.dumps(dict(reason=str(error), rejected_proposal=getattr(error, 'proposal', None)))
    raise ValueError('GLM could not prove a suitable variation; your current level was kept. Try again.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('approve', 'glm', 'update'))
    parser.add_argument('level', type=int)
    args = parser.parse_args()
    if not 1 <= args.level <= 174:
        parser.error('level is outside the editor')
    try:
        if args.action == 'update':
            update()
        else:
            (approve if args.action == 'approve' else modify)(args.level)
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else 'The request failed; your level was kept. Retry when the connection is ready.'
        path = DRAFTS / (f'{args.level:03}.glm-status' if args.action == 'glm' else 'publish-status')
        atomic(path, message[:220])
        raise SystemExit(1)
