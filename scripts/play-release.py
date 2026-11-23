#!/usr/bin/env python3
"""Send one released Play bundle to internal testing, then closed testing.

A rehearsal opens an edit, lets Google Play check the bundle and the release
as far as an uncommitted edit allows, and deletes the edit: nothing is sent.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'xyz.waozi.shovey'
UPLOAD = 'https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications/'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def notes(version, changelog):
    """This version's changelog section; Play keeps at most 500 characters per language."""
    section = re.search(r'^## \[' + re.escape(version) + r'\] - .*?\n(.*?)(?=^## |\Z)', changelog, re.M | re.S)
    text = section[1].strip()
    return text if len(text) <= 500 else text[:499] + '…'


def call(play, method, path, body=None):
    status, answer = play.call(method, path, body)
    if status != 200:
        raise RuntimeError(f'Play {method} {path}: HTTP {status}: {answer}')
    return answer


def send_bundle(play, edit, bundle):
    """Google Play's answer to the bundle: (HTTP status, its description or refusal)."""
    request = urllib.request.Request(f'{UPLOAD}{play.package}/edits/{edit}/bundles?uploadType=media',
                                     method='POST', data=bundle.read_bytes())
    request.add_header('Authorization', 'Bearer ' + play.token)
    request.add_header('Content-Type', 'application/octet-stream')
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace')


def internal_release(version, code, text):
    return {'track': 'internal', 'releases': [{'name': version, 'versionCodes': [code], 'status': 'completed',
                                               'releaseNotes': [{'language': 'en-US', 'text': text}]}]}


def on_internal(tracks, version, code):
    internal = next((t for t in tracks if t['track'] == 'internal'), {})
    return any(r.get('name') == version and r.get('versionCodes') == [code] and r.get('status') == 'completed'
               for r in internal.get('releases', []))


def publish(play, bundle, version, code, text, rehearse, send=send_bundle):
    """Whether this version is on internal testing afterwards. A rehearsal never commits."""
    edit = call(play, 'POST', '/edits', {})['id']
    committed = False
    try:
        tracks = call(play, 'GET', f'/edits/{edit}/tracks').get('tracks', [])
        if on_internal(tracks, version, code) and not rehearse:
            print(f'Shovey {version} ({code}) is already on internal testing; nothing is uploaded again')
            return True
        status, answer = send(play, edit, bundle)
        if status != 200:
            # Google Play refuses a version code it already holds; that is its
            # answer to rehearsing a version that has been released.
            if rehearse and 'already been used' in str(answer):
                print(f'Google Play read the bundle and refused version code {code} as already used')
                return on_internal(tracks, version, code)
            raise RuntimeError(f'Play bundle upload: HTTP {status}: {answer}')
        if str(answer.get('versionCode')) != code:
            raise RuntimeError(f'Play read version code {answer.get("versionCode")}, not {code}')
        call(play, 'PUT', f'/edits/{edit}/tracks/internal', internal_release(version, code, text))
        call(play, 'POST', f'/edits/{edit}:validate', {})
        if rehearse:
            print(f'Google Play accepted the bundle and validated internal testing for {version} ({code})')
            return False
        call(play, 'POST', f'/edits/{edit}:commit', {})
        committed = True
        print(f'Shovey {version} ({code}) is on internal testing')
        return True
    finally:
        if not committed:
            play.call('DELETE', f'/edits/{edit}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('account', type=Path, help='Google Play service account JSON file')
    parser.add_argument('bundle', type=Path, help='signed Google Play edition bundle')
    parser.add_argument('--entity', type=Path, required=True, help="the locked Entity package's checkout")
    parser.add_argument('--rehearse', action='store_true', help='check with Google Play and send nothing')
    args = parser.parse_args()
    if os.environ.get('GITEA_ACTIONS') != 'true':
        raise SystemExit('Google Play is reached only from the Downloads workflow')
    release = json.loads((ROOT / 'version.json').read_text())
    version, code = release['version'], str(release['version_code'])
    if args.bundle.name != f'shovey-v{version}-gplay.aab':
        raise SystemExit('Only this version\'s Google Play edition bundle is uploaded')
    text = notes(version, (ROOT / 'src/CHANGELOG.md').read_text())
    provider = load(args.entity / 'tools/play_dew_products.py', 'play_dew')
    promotion = load(ROOT / 'scripts/play-promote.py', 'play_promote')
    play = provider.Play(str(args.account), PACKAGE)
    publish(play, args.bundle, version, code, text, args.rehearse)
    # Add the 10 Dew pack at its premium; larger packs keep their prices. A
    # rehearsal only reads the prices it would save.
    products = [str(args.account), PACKAGE, '--pack', '10', *([] if args.rehearse else ['--apply'])]
    for attempt in (1, 2, 3):
        # Saving a fixed product and activating its buy option can be repeated
        # after a temporary Play failure; the upload above never is.
        try:
            provider.main(products)
            break
        except (RuntimeError, OSError) as error:
            if attempt == 3:
                raise
            print(f'Dew product setup incomplete ({error}); retrying in {attempt * 10} seconds', flush=True)
            time.sleep(attempt * 10)
    promotion.promote(play, version, code, inspect_only=args.rehearse)


if __name__ == '__main__':
    main()
