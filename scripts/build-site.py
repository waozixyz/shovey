#!/usr/bin/env python3
"""Build shovey.waozi.xyz from a published Shovey release.

The page runs that release's own shovey.zx, shovey.json and entity.zx from its
Linux download, unchanged, in Shovey's player compiled for the browser
(scripts/player.py site). It is the game players download, with the same
covers. Without --download the newest published release is fetched with gh.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import player

RELEASE_FILES = ('shovey.zx', 'shovey.json', 'entity.zx')


def newest_release():
    tags = json.loads(subprocess.check_output(
        ['gh', 'release', 'list', '--repo', 'waozixyz/shovey', '--limit', '20',
         '--exclude-drafts', '--json', 'tagName,isPrerelease'], text=True))
    for release in tags:
        if not release['isPrerelease'] and release['tagName'].startswith('v'):
            return release['tagName']
    raise SystemExit('No published Shovey release')


def download(tag, work):
    """The release's Linux download, unpacked: only the files the page runs."""
    version = tag[1:]
    archive = f'shovey-v{version}-linux-x86_64.tar.gz'
    subprocess.run(['gh', 'release', 'download', tag, '--repo', 'waozixyz/shovey',
                    '--pattern', archive, '--dir', str(work)], check=True)
    folder = work / 'shovey'
    folder.mkdir()
    with tarfile.open(work / archive) as packed:
        for name in RELEASE_FILES:
            member = packed.getmember('shovey/' + name)
            if not member.isfile():
                raise SystemExit(f'{archive} has no file shovey/{name}')
            (folder / name).write_bytes(packed.extractfile(member).read())
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', type=Path, help='an unpacked release folder (shovey.zx, shovey.json, entity.zx)')
    parser.add_argument('--tag', help='the release to fetch, by default the newest published one')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/web-site')
    parser.add_argument('--pictures', type=Path,
                        help="only write the loading screen's small pictures into this folder (make web)")
    args = parser.parse_args()
    if args.pictures:
        player.page_pictures(args.pictures)
        return
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
        work = Path(temporary)
        tag = args.tag or (None if args.download else newest_release())
        release = args.download.resolve() if args.download else download(tag, work)
        version = json.loads((release / 'shovey.json').read_text())['version']
        if tag and tag != 'v' + version:
            raise SystemExit(f'{tag} carries Shovey {version}')
        player.site(release, args.output)


if __name__ == '__main__':
    main()
