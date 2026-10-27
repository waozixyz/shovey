#!/usr/bin/env python3
"""Build shovey.waozi.xyz from a published Shovey release.

The page runs that release's own shovey.zx, shovey.json and entity.zx from its
Linux download, unchanged, in Arcade's browser host, as arcade.waozi.xyz runs
the published Arcade. It is the game players download, with the same covers.
Without --download the newest published release is fetched with gh.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# The page's own files beside site/: published name, source in this checkout.
PAGE_FILES = {
    'privacy.html': 'src/web/privacy.html',
    'og.png': 'assets/branding/shovey-social.png',
}
# Pictures the loading screen shows, as small copies: (published name,
# source, longest edge). The title art is a JPEG; the logo and icon keep
# their transparency or crisp edges as PNG.
PAGE_PICTURES = [
    ('icon.png', 'assets/branding/shovey-icon.png', 512),
    ('icon-192.png', 'assets/branding/shovey-icon.png', 192),
    ('logo.png', 'assets/shovey/logo.png', 720),
    ('title-landscape.jpg', 'assets/shovey/title-landscape.png', 1280),
    ('title-portrait.jpg', 'assets/shovey/title-portrait.png', 1280),
]


def small_picture(source, target, longest):
    with Image.open(source) as image:
        image.load()
        alpha = 'A' in image.getbands()
        image = image.convert('RGBA' if alpha else 'RGB')
        scale = min(1.0, longest / max(image.size))
        if scale < 1.0:
            image = image.resize((round(image.width * scale), round(image.height * scale)),
                                 Image.Resampling.LANCZOS)
        if target.suffix == '.jpg':
            image.save(target, 'JPEG', quality=82, optimize=True, progressive=True)
        else:
            image.save(target, 'PNG', optimize=True)
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
    parser.add_argument('--arcade', type=Path, help="Arcade's checkout, whose host runs the game")
    parser.add_argument('--download', type=Path, help='an unpacked release folder (shovey.zx, shovey.json, entity.zx)')
    parser.add_argument('--tag', help='the release to fetch, by default the newest published one')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/web-site')
    parser.add_argument('--pictures', type=Path,
                        help="only write the loading screen's small pictures into this folder (make web)")
    args = parser.parse_args()
    if args.pictures:
        args.pictures.mkdir(parents=True, exist_ok=True)
        for name, source, longest in PAGE_PICTURES:
            small_picture(ROOT / source, args.pictures / name, longest)
        return
    if not args.arcade:
        parser.error('--arcade is required to build the site')
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
        work = Path(temporary)
        tag = args.tag or (None if args.download else newest_release())
        release = args.download.resolve() if args.download else download(tag, work)
        version = json.loads((release / 'shovey.json').read_text())['version']
        if tag and tag != 'v' + version:
            raise SystemExit(f'{tag} carries Shovey {version}')
        site = work / 'site'
        shutil.copytree(ROOT / 'site', site)
        for name, source in PAGE_FILES.items():
            shutil.copyfile(ROOT / source, site / name)
        for name, source, longest in PAGE_PICTURES:
            small_picture(ROOT / source, site / name, longest)
        subprocess.run([sys.executable, 'scripts/build-web.py', '--shovey', str(release),
                        '--site', str(site), '--output', str(args.output.resolve())],
                       cwd=args.arcade, check=True)
    (args.output / 'build.json').write_text(json.dumps({'version': version}) + '\n')
    print(f'shovey.waozi.xyz runs the released Shovey {version} in {args.output}')


if __name__ == '__main__':
    main()
