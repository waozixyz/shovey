"""Prepare the editor's module imports without campaign board previews."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if len(sys.argv) != 3:
    raise SystemExit('Usage: prepare_editor_assets.py ASSETS GENERATED_MODULES')
# Shared board rules import levels; unused campaign procedures are pruned by
# the compiler. The editor has no campaign loader or preview inventory.
generated = Path(sys.argv[2]).resolve()
generated.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, str(ROOT / 'tools/levels/levels.py'), 'generate',
                '--output', str(generated / 'levels.zi')], cwd=ROOT, check=True)
