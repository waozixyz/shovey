#!/usr/bin/env python3
"""Publish only the tested approved campaign, then read and prove it again."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

from editor_server import live_campaign_snapshot

ROOT = Path(__file__).resolve().parents[1]


def verify_campaign(config, document, answer, verify_route):
    proof = live_campaign_snapshot(config, answer, verify_route)
    if answer.get('document') != document:
        raise ValueError('The server campaign differs from this approved revision')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'build/campaign-publisher/publication')
    parser.add_argument('--solver', type=Path, default=ROOT / 'build/solver/shovey-solve-classic')
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--check', action='store_true', help='Prove the local document without publishing')
    parser.add_argument('--verify-only', action='store_true', help='Read and prove the served campaign')
    args = parser.parse_args()
    config = json.loads((ROOT / 'levels/publication.json').read_text())
    if config['server'] != 'https://api.waozi.xyz' or config['format'] != 'shovey-campaign-1':
        raise ValueError('Unexpected campaign publication destination')
    document = json.loads((ROOT / 'levels/approved.json').read_text())

    def verify_route(number, board, route):
        result = subprocess.run([str(args.solver.resolve()), 'verify', '--level', str(number), board, route],
                                capture_output=True, timeout=10)
        return result.returncode == 0

    local = dict(publication=dict(id=config['id'], format=config['format'],
                                 author=dict(public_id=config['author']), visibility='public',
                                 levels=len(document['levels'])), document=document)
    verify_campaign(config, document, local, verify_route)
    payload = json.dumps(document, separators=(',', ':'), ensure_ascii=False).encode()
    if args.check:
        print(f'Approved campaign: {len(document["levels"])} winning routes verified locally')
        return
    if not args.verify_only:
        if args.key_file is None or not args.key_file.is_file():
            raise ValueError('A campaign publisher key file is required')
        with tempfile.TemporaryDirectory(prefix='shovey-campaign-') as folder:
            campaign = Path(folder) / 'campaign.json'
            campaign.write_bytes(payload)
            result = subprocess.run([str(args.client.resolve()), 'publish', str(args.key_file.resolve()),
                                     config['server'], config['format'], config['title'], str(campaign), config['id']],
                                    capture_output=True, timeout=90)
            if result.returncode:
                raise RuntimeError(f'Campaign publication client failed (exit {result.returncode})')
    url = config['server'] + '/api/v1/publications/' + config['id']
    last_error = None
    for attempt in range(6):
        try:
            # Use the same HTTP transport as the native publication client.
            response = subprocess.run(['curl', '--fail', '--silent', '--show-error',
                                       '--max-time', '20', '-H', 'Cache-Control: no-cache', url],
                                      capture_output=True, timeout=25)
            if response.returncode:
                raise OSError(f'Campaign readback failed (curl exit {response.returncode})')
            body = response.stdout
            if len(body) > 2 * 1024 * 1024:
                raise ValueError('The server campaign response is too large')
            verify_campaign(config, document, json.loads(body), verify_route)
            print(f'Live campaign verified: all {len(document["levels"])} approved boards and winning routes match')
            return
        except (ValueError, OSError) as error:
            last_error = error
            if attempt < 5:
                time.sleep(2)
    raise RuntimeError('The published campaign could not be verified') from last_error


if __name__ == '__main__':
    main()
