#!/usr/bin/env python3
"""Prepare Daochi's map registration JSON from an approved campaign snapshot.

This command only writes JSON to stdout. Registration uses the publisher's
existing admin authorization separately. Keep each source snapshot: a changed
map has a different identity, while changing its stored solution does not.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


GAME = 'shovey.classic'
HASH_DOMAIN = b'shovey.classic.map.v1\n'
LAYERS = ('cells', 'tiles', 'decorations')


def level_number(number):
    if type(number) is not int or not 1 <= number <= 4096:
        raise ValueError('Map level must be an integer from 1 to 4096')
    return number


def map_hash(number, board):
    level_number(number)
    if not isinstance(board, str) or not re.fullmatch('[0-9a-f]{1440}', board):
        raise ValueError('Map must contain exactly 1440 lowercase hex characters')
    # Hash the original three layers, before the engine interprets them.
    # These are actual LF bytes, with no newline after the board.
    preimage = HASH_DOMAIN + str(number).encode('ascii') + b'\n' + board.encode('ascii')
    return hashlib.sha256(preimage).hexdigest()


def map_data(level):
    layers = []
    for name in LAYERS:
        rows = level.get(name)
        if (not isinstance(rows, list) or len(rows) != 20 or
                any(not isinstance(row, str) or not re.fullmatch('[0-9a-f]{24}', row)
                    for row in rows)):
            raise ValueError(f'Map {level.get("number")}: {name} needs 20 rows of 24 lowercase hex characters')
        layers.append(''.join(rows))
    return ''.join(layers)


def registration(campaign, source_version):
    if not isinstance(source_version, str) or not source_version.strip():
        raise ValueError('An explicit source version is required')
    if not isinstance(campaign, dict) or not isinstance(campaign.get('levels'), list):
        raise ValueError('Approved snapshot must contain a levels array')
    maps = []
    seen = set()
    for level in campaign['levels']:
        if not isinstance(level, dict):
            raise ValueError('Each approved map must be an object')
        number = level_number(level.get('number'))
        if number in seen:
            raise ValueError(f'Duplicate map level {number}')
        seen.add(number)
        board = map_data(level)
        maps.append(dict(level=number, map_hash=map_hash(number, board), map=board))
    return dict(game=GAME, source_version=source_version, maps=maps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved', type=Path, required=True,
                        help='Exact approved JSON snapshot from the source being published')
    parser.add_argument('--source-version', required=True,
                        help='Release or campaign identifier for this snapshot')
    args = parser.parse_args()
    try:
        payload = registration(json.loads(args.approved.read_text()), args.source_version)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
