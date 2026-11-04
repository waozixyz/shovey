#!/usr/bin/env python3
"""Verify the existing node delivery serves the Island package buyers request."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://api.waozi.xyz'


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
    parser.add_argument('--descriptor', type=Path, default=ROOT / 'packaging/island.json')
    args = parser.parse_args()
    verify(json.loads(args.descriptor.read_bytes()))
    print('Live Island catalog matches the released package; its compiled bytes exist behind the buyer gate')
