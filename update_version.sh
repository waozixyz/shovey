#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 - "$@" <<'PY'
import argparse
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser(description='Synchronize Shovey release metadata from its changelog and Arcade ledger')
parser.add_argument('--arcade', type=Path, default=Path('../arcade'))
args = parser.parse_args()
match = re.search(r'^## \[([0-9]+\.[0-9]+\.[0-9]+)\]', Path('src/CHANGELOG.md').read_text(), re.M)
if match is None:
    raise SystemExit('src/CHANGELOG.md needs a numeric release entry')
release = json.loads((args.arcade / 'apps/versions.json').read_text())['node_apps']['shovey']
if release['version'] != match[1]:
    raise SystemExit('Update the Arcade ledger for Shovey ' + match[1] + ' first')
path = Path('version.json')
path.write_text(json.dumps(dict(version=match[1], version_code=release['sequence']), indent=2) + '\n')
print('Shovey release metadata synchronized:', match[1], 'code', release['sequence'])
PY
