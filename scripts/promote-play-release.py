#!/usr/bin/env python3
"""Promote an exact, already completed internal release from GitHub Actions."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

PACKAGE = 'xyz.waozi.shovey'


def production_release(tracks, version, code):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric release version')
    if not re.fullmatch(r'[1-9][0-9]*', code):
        raise ValueError('Use a positive version code')
    internal = next((t for t in tracks if t['track'] == 'internal'), {})
    source = [r for r in internal.get('releases', [])
              if r.get('name') == version and r.get('versionCodes') == [code]
              and r.get('status') == 'completed']
    if len(source) != 1:
        raise ValueError('The exact approved version must be completed on internal testing')
    production = next((t for t in tracks if t['track'] == 'production'), {})
    existing = production.get('releases', [])
    if existing:
        if (len(existing) == 1 and existing[0].get('name') == version
                and existing[0].get('versionCodes') == [code]
                and existing[0].get('status') == 'completed'):
            return None
        raise ValueError('Production has another release; this first-launch workflow will not replace it')
    release = copy.deepcopy(source[0])
    release['status'] = 'completed'
    release.pop('userFraction', None)
    return {'track': 'production', 'releases': [release]}


def promote(play, version, code):
    def call(method, path, body=None):
        status, answer = play.call(method, path, body)
        if status != 200:
            raise RuntimeError(f'Play {method} {path}: HTTP {status}: {answer}')
        return answer

    edit = call('POST', '/edits', {})['id']
    committed = False
    try:
        tracks = call('GET', f'/edits/{edit}/tracks')['tracks']
        update = production_release(tracks, version, code)
        if update is not None:
            call('PUT', f'/edits/{edit}/tracks/production', update)
            call('POST', f'/edits/{edit}:validate', {})
            call('POST', f'/edits/{edit}:commit', {})
            committed = True
    finally:
        if not committed:
            play.call('DELETE', f'/edits/{edit}')

    verification = call('POST', '/edits', {})['id']
    try:
        tracks = call('GET', f'/edits/{verification}/tracks')['tracks']
        if production_release(tracks, version, code) is not None:
            raise RuntimeError('Fresh Play readback did not confirm the public release')
    finally:
        play.call('DELETE', f'/edits/{verification}')
    return {'package': PACKAGE, 'version': version, 'version_code': code,
            'track': 'production', 'status': 'completed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--version-code', required=True)
    parser.add_argument('--entity-tools', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Shovey Play publishing runs only through GitHub Actions')
    spec = importlib.util.spec_from_file_location('play_dew', args.entity_tools / 'play_dew_products.py')
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    # NamedTemporaryFile is private and removes the service credential afterward.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as key:
        key.write(os.environ['GOOGLE_PLAY_SERVICE_ACCOUNT_JSON'])
        key.flush()
        play = provider.Play(key.name, PACKAGE)
        print(json.dumps(promote(play, args.version, args.version_code)))


if __name__ == '__main__':
    main()
