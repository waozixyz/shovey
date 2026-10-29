#!/usr/bin/env python3
"""Check the live signed release against the exact campaign published by this editor."""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publication_queue import Queue, atomic
from level_rules import validate_star_spacing

ROOT = Path(__file__).resolve().parents[1]


def campaign_boards(release, receipt, cached, history=None):
    """Only reuse boards tied to this exact signed server release."""
    if receipt.get('phase') in ('published', 'verified') and receipt.get('release') == release:
        boards = receipt.get('approved_boards')
    elif cached.get('release') == release:
        boards = cached.get('boards')
    elif history and history.get('release') == release:
        boards = history.get('boards')
    else:
        raise ValueError('Server campaign is not in the verified publication history')
    if not isinstance(boards, list) or not 1 <= len(boards) <= 175 or any(
            not isinstance(board, str) or not re.fullmatch('[0-9a-f]{1440}', board) for board in boards):
        raise ValueError('The published campaign snapshot is incomplete')
    return boards


def history_path(root, release):
    digest = hashlib.sha256(json.dumps(release, sort_keys=True).encode()).hexdigest()
    return root / 'backup/approved-publications' / (digest + '.json')


def remember_verified(root, receipt):
    """Called only after the publisher verifies this exact signed artifact."""
    release = receipt['release']
    boards = campaign_boards(release, receipt, {})
    snapshot = dict(status='verified', checked_at=int(time.time()), release=release, boards=boards)
    path = history_path(root, release)
    if path.exists() and campaign_boards(release, {}, {}, read_json(path)) != boards:
        raise ValueError('The verified release already has a different campaign snapshot')
    atomic(path, json.dumps(snapshot, separators=(',', ':')) + '\n')
    # The next build may start immediately; the editor need not catch the
    # fleeting interval when approved-publication.json says "verified".
    atomic(root / 'backup/editor-drafts/server-campaign.json', json.dumps(snapshot, separators=(',', ':')) + '\n')


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def live_campaign_snapshot(config, answer, verify_route, previous=None):
    """Verify the campaign players download, independently of any release."""
    publication = answer.get('publication', {})
    author = publication.get('author', {})
    if (config.get('format') != 'shovey-campaign-1' or
            not re.fullmatch('[0-9a-f]{32}', config.get('id', '')) or
            not re.fullmatch('[0-9a-f]{64}', config.get('author', '')) or
            publication.get('id') != config['id'] or
            publication.get('format') != config['format'] or
            author.get('public_id') != config['author'] or
            publication.get('visibility') != 'public'):
        raise ValueError('The live campaign identity differs from this publisher')
    document = answer.get('document', {})
    levels = document.get('levels', [])
    if (document.get('edition') != 'classic' or not isinstance(levels, list) or
            not 1 <= len(levels) <= 175 or publication.get('levels') != len(levels)):
        raise ValueError('The live campaign is incomplete')
    boards, routes = [], []
    for number, level in enumerate(levels, 1):
        if level.get('number') != number:
            raise ValueError('The live campaign has missing or duplicate levels')
        layers = []
        for key in ('cells', 'tiles', 'decorations'):
            rows = level.get(key)
            if (not isinstance(rows, list) or len(rows) != 20 or
                    any(not isinstance(row, str) or not re.fullmatch('[0-9a-f]{24}', row) for row in rows)):
                raise ValueError('The live campaign has an invalid board')
            layers.extend(rows)
        validate_star_spacing([int(''.join(level['cells'])[at:at + 2], 16)
                               for at in range(0, 480, 2)], f'Classic {number}')
        route = level.get('solution')
        if not isinstance(route, str) or not re.fullmatch('[0123ft]{1,60000}', route):
            raise ValueError('The live campaign has no winning route')
        boards.append(''.join(layers))
        routes.append(route)
    digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = dict(id=config['id'], author=config['author'])
    previous = previous or {}
    already_verified = (previous.get('source') == 'live-campaign' and
                        previous.get('publication') == identity and
                        previous.get('document_sha256') == digest and previous.get('boards') == boards)
    if not already_verified:
        deadline = time.monotonic() + 30
        for number, (board, route) in enumerate(zip(boards, routes), 1):
            if time.monotonic() > deadline or not verify_route(number, board, route):
                raise ValueError(f'The live campaign route does not win at level {number}')
    return dict(status='verified', source='live-campaign', checked_at=int(time.time()),
                publication=identity, document_sha256=digest, boards=boards)


def read_live_campaign(config, previous):
    from editor_actions import verify_route
    request = urllib.request.Request(config['server'].rstrip('/') + '/api/v1/publications/' + config['id'],
                                     headers={'User-Agent': 'Shovey Editor', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ValueError('The live campaign is too large')
    return live_campaign_snapshot(config, json.loads(body), verify_route, previous)


def check(root=ROOT):
    state = root / 'backup/editor-drafts'
    config_path = root / 'backup/editor-publish.json'
    if not config_path.exists():
        return
    Queue(root).reconcile()
    with (state / 'server-check.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        cache_path = state / 'server-campaign.json'
        try:
            previous = read_json(cache_path)
        except (OSError, ValueError):
            previous = {}
        try:
            live_config = root / 'backup/campaign-publisher/publication.json'
            if not live_config.is_file():
                raise ValueError('No live campaign publisher is set up')
            result = read_live_campaign(read_json(live_config), previous)
        except Exception as error:
            # Keep the previous authenticated snapshot for a later retry, but
            # do not claim a fresh server match when this check failed.
            result = previous | dict(status='unavailable', checked_at=int(time.time()))
            print(f'Server check unavailable: {error}', flush=True)
        temporary = cache_path.with_suffix('.json.new')
        temporary.write_text(json.dumps(result, separators=(',', ':')) + '\n')
        temporary.replace(cache_path)


if __name__ == '__main__':
    check()
