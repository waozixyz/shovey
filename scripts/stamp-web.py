"""Identify the built game and keep browser caches on the same revision."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
approved = json.loads((root / 'levels/approved.json').read_text())['levels']
output = root / 'build/web'
page = output / 'index.html'
page.write_text(page.read_text().replace('__SHOVEY_REVISION__', revision))
(output / 'build.json').write_text(json.dumps({
    'revision': revision,
    'classic_levels': len(approved),
}) + '\n')
