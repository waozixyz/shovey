#!/usr/bin/env python3
"""Pin the Arcade commit, and its locked Ziran, that build the Android APK.

The pinned commit must record this release in apps/versions.json, so the
publisher pins the Arcade commit it has just recorded and pushed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'packaging/android'
HOST = 'https://github.com/waozixyz/arcade.git'


def package_id(url, commit):
    return 'p' + hashlib.sha256(f'{url}\n{commit}'.encode()).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('commit', help='Full Arcade commit that records this Shovey release')
    parser.add_argument('--arcade', type=Path, default=ROOT.parent / 'arcade', help='Arcade checkout')
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', args.commit + '^{commit}'],
                                     cwd=args.arcade, text=True).strip()
    # Builders fetch the pin from GitHub, so it must already be pushed.
    subprocess.run(['git', 'merge-base', '--is-ancestor', commit, 'origin/master'], cwd=args.arcade, check=True)
    toolchain = json.loads(subprocess.check_output(['git', 'show', commit + ':ziran.lock'],
                                                   cwd=args.arcade, text=True))['toolchain']
    manifest = (PROJECT / 'ziran.toml').read_text()
    manifest = re.sub(r'(\[toolchain\]\ngit = "[^"]+"\nref = ")[0-9a-f]{40}"', r'\g<1>' + toolchain['commit'] + '"', manifest)
    manifest = re.sub(r'(\[dependencies\.host\]\ngit = "[^"]+"\nref = ")[0-9a-f]{40}"', r'\g<1>' + commit + '"', manifest)
    # Replace the pinned values in place, keeping the lock in Ziran's format.
    text = (PROJECT / 'ziran.lock').read_text()
    lock = json.loads(text)
    host = lock['packages'][0]
    assert host['name'] == 'host' and host['url'] == HOST and lock['toolchain']['url'] == toolchain['url']
    for old, new in ((host['id'], package_id(HOST, commit)), (host['commit'], commit),
                     (lock['toolchain']['commit'], toolchain['commit'])):
        text = text.replace('"' + old + '"', '"' + new + '"')
    (PROJECT / 'ziran.toml').write_text(manifest)
    (PROJECT / 'ziran.lock').write_text(text)
    print(f'Android host: Arcade {commit}, Ziran {toolchain["commit"]}')


if __name__ == '__main__':
    main()
