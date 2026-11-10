#!/usr/bin/env python3
"""Verify the existing node delivery serves the Island package buyers request."""
import argparse
import json
import re
from pathlib import Path
import subprocess
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://api.waozi.xyz'


def released_descriptor(request=subprocess.run):
    """Read the descriptor at the published tag's immutable source revision.

    Master can contain a rebuilt, unreleased Island with a different digest.
    The live catalog must serve the package that released players request.
    """
    repository = 'repos/waozixyz/shovey/'

    def github(path):
        response = request(['gh', 'api', '--hostname', 'github.com',
                            '-H', 'Accept: application/vnd.github.raw+json',
                            repository + path], check=True, capture_output=True)
        return json.loads(response.stdout)

    release = github('releases/latest')
    tag = release.get('tag_name', '')
    if release.get('draft') or release.get('prerelease') or not tag.startswith('v'):
        raise ValueError('Expected a published stable Shovey release')
    revision = github('commits/' + quote(tag, safe='')).get('sha', '')
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Released Shovey source must resolve to a full commit')
    descriptor = github('contents/packaging/island.json?ref=' + revision)
    return descriptor, tag, revision


def verify(descriptor, request=subprocess.run):
    route = ORIGIN + '/api/v2/packages/' + descriptor['package_id']
    latest = request(['curl', '--fail', '--silent', '--show-error', '--max-time', '30',
                      '--max-filesize', '65536', '-H', 'Cache-Control: no-cache',
                      route + '/latest?bucket=0&format=zx'],
                     check=True, capture_output=True)
    value = json.loads(latest.stdout)
    expected = dict(variant='module', sha256=descriptor['sha256'], size=descriptor['bytes'])
    if value.get('app_id') != descriptor['package_id'] or value.get('version') != descriptor['version'] or \
            value.get('artifacts') != [expected]:
        raise ValueError('Live Island catalog differs from packaging/island.json; publish its reviewed compiled package first')
    # An absent package returns 404. The existing product gate returns 403;
    # testing just the public catalog would miss the broken buyer download.
    response = request(['curl', '--silent', '--show-error', '--max-time', '30',
                        '--max-filesize', '65536', '--output', '/dev/null',
                        '--write-out', '%{http_code}', '-H', 'Cache-Control: no-cache',
                        route + '/' + descriptor['sha256'] + '.zx'],
                       check=True, capture_output=True)
    if response.stdout.strip() != b'403':
        raise ValueError('Island package must exist behind its product gate (expected HTTP 403)')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--descriptor', type=Path, help='Check an explicit Island descriptor')
    source.add_argument('--released', action='store_true',
                        help='Check the latest published Shovey release instead of this checkout')
    args = parser.parse_args()
    if args.released:
        descriptor, tag, revision = released_descriptor()
        print(f'Checking Island for {tag}: https://github.com/waozixyz/shovey/blob/{revision}/packaging/island.json', flush=True)
    else:
        descriptor = json.loads((args.descriptor or ROOT / 'packaging/island.json').read_bytes())
    verify(descriptor)
    print('Live Island catalog matches the released package; its compiled bytes exist behind the buyer gate')
