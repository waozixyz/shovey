"""Identify the built game and keep browser caches on the same revision."""
import json
import re
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
approved = json.loads((root / 'levels/approved.json').read_text())['levels']
output = root / 'build/web'
page = output / 'index.html'
release = re.search(r'^## \[([0-9]+(?:\.[0-9]+)+)\] - (\d{4}-\d{2}-\d{2})',
                    (root / 'src/CHANGELOG.md').read_text(), re.M)
assert release, 'The game needs a numeric release and date'
version, release_date = release.groups()
wasm_bytes = (output / 'runtime.wasm').stat().st_size
page.write_text(page.read_text().replace('__SHOVEY_REVISION__', revision)
                .replace('__SHOVEY_LEVEL_COUNT__', str(len(approved)))
                .replace('__SHOVEY_VERSION__', version)
                .replace('__SHOVEY_RELEASE_DATE__', release_date)
                .replace('__SHOVEY_WASM_BYTES__', str(wasm_bytes)))
(output / 'build.json').write_text(json.dumps({
    'revision': revision,
    'classic_levels': len(approved),
    'version': version,
    'release_date': release_date,
    'wasm_bytes': wasm_bytes,
}) + '\n')
