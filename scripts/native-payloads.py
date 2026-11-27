#!/usr/bin/env python3
"""Reuse portable release payloads between native jobs of one exact-source run."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import player


def names(receipt):
    return ['shovey.zx', 'shovey.json', 'entity.zx', *receipt['local_bundles'].values()]


def save(cache, revision):
    receipt = player.checked_collection()
    if cache.exists():
        raise ValueError('Portable payload handoff already exists')
    cache.mkdir(parents=True)
    player.stage_collection_data(cache, receipt)
    files = {name: dict(bytes=(cache / name).stat().st_size, sha256=player.digest(cache / name))
             for name in names(receipt)}
    (cache / 'manifest.json').write_text(json.dumps(dict(revision=revision, files=files)) + '\n')
    print('Saved verified portable payloads for', revision)


def restore(cache, revision):
    if not cache.exists():
        print('No portable payload handoff; build the collection normally')
        return False
    manifest = json.loads((cache / 'manifest.json').read_text())
    if manifest['revision'] != revision:
        raise ValueError('Portable payloads belong to another source revision')
    # Read only the fixed receipt path before validating all payload paths.
    receipt = json.loads((cache / 'shovey.json').read_text())
    player.verify_local_bundles(cache, receipt)
    if not receipt.get('island_bundled') or receipt['version'] != player.release()['version']:
        raise ValueError('Portable payloads are not this desktop release')
    expected = names(receipt)
    if set(manifest['files']) != set(expected):
        raise ValueError('Portable payload manifest has unexpected files')
    for name in expected:
        path = cache / name
        info = manifest['files'][name]
        if path.stat().st_size != info['bytes'] or player.digest(path) != info['sha256']:
            raise ValueError('Portable payload changed: ' + name)
    if player.digest(cache / 'shovey.zx') != receipt['sha256']:
        raise ValueError('Portable collection does not match its receipt')
    # Validate everything before replacing build outputs. No native binaries or
    # platform libraries travel between jobs; those are compiled by each host.
    for name in expected:
        target = player.OUT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.new')
        shutil.copyfile(cache / name, temporary)
        temporary.replace(target)
    player.checked_collection()
    print('Reused verified portable payloads for', revision)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['save', 'restore'])
    args = parser.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=player.ROOT, text=True).strip()
    handoff = Path(os.environ['HANDOFF'])
    if revision != os.environ['GITHUB_SHA'] or (handoff / 'revision').read_text().strip() != revision:
        raise ValueError('Portable payload handoff is not this checkout')
    if os.environ.get('KRYON_TEST_DRIVER') == '1' or os.environ.get('SHOVEY_DEBUG'):
        raise ValueError('Only production payloads can be handed off')
    cache = handoff / 'portable'
    if args.mode == 'save':
        save(cache, revision)
    elif not restore(cache, revision):
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
