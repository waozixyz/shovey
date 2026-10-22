#!/usr/bin/env python3
"""Check the live signed release against the exact campaign published by this editor."""
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]


def campaign_boards(release, receipt, cached):
    """Only reuse boards tied to this exact signed server release."""
    if receipt.get('phase') in ('published', 'verified') and receipt.get('release') == release:
        boards = receipt.get('approved_boards')
    elif cached.get('release') == release:
        boards = cached.get('boards')
    else:
        raise ValueError('Server campaign is not in the verified publication history')
    if not isinstance(boards, list) or not 1 <= len(boards) <= 175 or any(
            not isinstance(board, str) or not re.fullmatch('[0-9a-f]{1440}', board) for board in boards):
        raise ValueError('The published campaign snapshot is incomplete')
    return boards


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def check(root=ROOT):
    state = root / 'backup/editor-drafts'
    config_path = root / 'backup/editor-publish.json'
    if not config_path.exists():
        return
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
            spec = importlib.util.spec_from_file_location('approved_publisher', root / 'scripts/publish-approved.py')
            workflow = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(workflow)
            config = read_json(config_path)
            publisher = workflow.release_publisher(Path(config['arcade']))
            release = publisher.served_release('https://api.waozi.xyz', 'inbe.arcade')
            pins = read_json(Path(config['inbe_source']) / 'apps/publishers.json')
            publisher.validate_release(release, 'inbe.arcade', pins)
            receipt = read_json(root / 'backup/approved-publication.json')
            boards = campaign_boards(release, receipt, previous)
            result = dict(status='verified', checked_at=int(time.time()), release=release, boards=boards)
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
