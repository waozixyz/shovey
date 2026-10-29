#!/bin/sh
# Synchronize version.json from the newest numeric release in
# src/CHANGELOG.md. The Android version code goes up by one with each new
# version, so every release installs over the previous one.
set -eu
cd "$(dirname "$0")"
python3 - <<'PY'
import json
from pathlib import Path
import re
match = re.search(r'^## \[([0-9]+\.[0-9]+\.[0-9]+)\]', Path('src/CHANGELOG.md').read_text(), re.M)
if match is None:
    raise SystemExit('src/CHANGELOG.md needs a numeric release entry')
path = Path('version.json')
previous = json.loads(path.read_text())
version = match[1]
old = tuple(map(int, previous['version'].split('.')))
new = tuple(map(int, version.split('.')))
if new < old:
    raise SystemExit('Release versions cannot decrease')
code = previous['version_code'] + (new > old)
path.write_text(json.dumps(dict(version=version, version_code=code), indent=2) + '\n')
print('Shovey release metadata synchronized:', version, 'code', code)
PY
