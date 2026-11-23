#!/usr/bin/env python3
"""Read Google Play's tracks and complete closed testing for one released version."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

CLOSED_TRACK = os.environ.get('CLOSED_TRACK', 'alpha')


def closed_release(tracks, version, code, target=CLOSED_TRACK):
    # This allowlist is deliberately independent of workflow inputs.
    if target != CLOSED_TRACK or target in ('production', 'internal', 'beta'):
        raise ValueError('Only the configured closed testing track may be promoted')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric release version')
    if not re.fullmatch(r'[1-9][0-9]*', code):
        raise ValueError('Use a positive version code')
    internal = next((t for t in tracks if t['track'] == 'internal'), {})
    source = [r for r in internal.get('releases', [])
              if r.get('name') == version and r.get('versionCodes') == [code]
              and r.get('status') == 'completed']
    if len(source) != 1:
        raise ValueError('The exact version must be completed on internal testing')
    closed = next((t for t in tracks if t['track'] == target), None)
    if closed is None:
        raise ValueError('Configured closed testing track is absent; inspect Play Console')
    existing = closed.get('releases', [])
    if (len(existing) == 1 and existing[0].get('name') == version
            and existing[0].get('versionCodes') == [code]
            and existing[0].get('status') == 'completed'
            and 'userFraction' not in existing[0]):
        return None
    if any(int(c) > int(code) for r in existing for c in r.get('versionCodes', [])):
        raise ValueError('Refusing to replace a newer closed testing release')
    release = copy.deepcopy(source[0])
    release['status'] = 'completed'
    release.pop('userFraction', None)
    return {'track': target, 'releases': [release]}


def call(play, method, path, body=None):
    status, answer = play.call(method, path, body)
    if status != 200:
        raise RuntimeError(f'Play {method} {path}: HTTP {status}: {answer}')
    return answer


def state(play, edit, label):
    tracks = call(play, 'GET', f'/edits/{edit}/tracks').get('tracks', [])
    testers = {}
    for track in tracks:
        name = track['track']
        if name != 'production':
            status, answer = play.call('GET', f'/edits/{edit}/testers/{name}')
            # Report the API response shape/count without publishing group addresses.
            testers[name] = {'http_status': status,
                             'api_fields': sorted(answer) if isinstance(answer, dict) else [],
                             'googleGroups_count': len(answer.get('googleGroups', [])) if isinstance(answer, dict) else 0}
            if status != 200:
                testers[name]['error'] = answer
    print(json.dumps({'phase': label, 'package': play.package,
                      'tracks': tracks, 'testers': testers}, sort_keys=True))
    return tracks


def promote(play, version, code, inspect_only=False):
    edit = call(play, 'POST', '/edits', {})['id']
    committed = False
    try:
        tracks = state(play, edit, 'before')
        if inspect_only:
            return
        update = closed_release(tracks, version, code)
        if update is not None:
            # Never construct a URL from a dispatch input or an API track name.
            call(play, 'PUT', f'/edits/{edit}/tracks/{CLOSED_TRACK}', update)
            call(play, 'POST', f'/edits/{edit}:validate', {})
            call(play, 'POST', f'/edits/{edit}:commit', {})
            committed = True
    finally:
        if not committed:
            play.call('DELETE', f'/edits/{edit}')
    verification = call(play, 'POST', '/edits', {})['id']
    try:
        tracks = state(play, verification, 'after')
        if closed_release(tracks, version, code) is not None:
            raise RuntimeError('Fresh API read did not confirm completed closed testing')
    finally:
        play.call('DELETE', f'/edits/{verification}')


def seal_credential(public_key, credential):
    import base64
    import ctypes
    sodium = ctypes.CDLL('libsodium.so.23')
    sodium.sodium_init()
    sodium.crypto_box_seal.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                       ctypes.c_ulonglong, ctypes.c_char_p]
    public = base64.b64decode(public_key, validate=True)
    if len(public) != 32:
        raise ValueError('Expected a GitHub repository public key')
    message = credential.encode()
    encrypted = ctypes.create_string_buffer(len(message) + 48)
    if sodium.crypto_box_seal(encrypted, message, len(message), public) != 0:
        raise RuntimeError('Credential encryption failed')
    return base64.b64encode(encrypted.raw)


def main():
    spec = importlib.util.spec_from_file_location(
        'play_dew', Path(os.environ.get('PLAY_ENTITY', 'play-entity')) / 'tools/play_dew_products.py')
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir='.') as key:
        key.write(os.environ['GOOGLE_PLAY_SERVICE_ACCOUNT_JSON'])
        key.flush()
        inspect_only = os.environ.get('INSPECT_ONLY') == 'true'
        packages = ('xyz.waozi.shovey', 'xyz.waozi.wurm') if inspect_only else (os.environ['PLAY_PACKAGE'],)
        for package in packages:
            promote(provider.Play(key.name, package),
                    os.environ.get('VERSION', ''), os.environ.get('VERSION_CODE', ''), inspect_only)
        public_key = os.environ.get('WURM_SECRET_PUBLIC_KEY')
        if public_key:
            if not inspect_only:
                raise ValueError('Credential setup is only available during inspection')
            # Seal directly to Wurm's GitHub repository public key. Only
            # ciphertext leaves this runner; no private key/token is exported.
            Path('wurm-play-secret.encrypted').write_bytes(
                seal_credential(public_key, os.environ['GOOGLE_PLAY_SERVICE_ACCOUNT_JSON']))


if __name__ == '__main__':
    main()
