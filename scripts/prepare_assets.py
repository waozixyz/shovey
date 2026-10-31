"""Prepare generated modules in the caller's directory without changing sources."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) != 3:
    raise SystemExit('Usage: prepare_assets.py ASSETS GENERATED_MODULES')
generated = Path(sys.argv[2]).resolve()
subprocess.run([sys.executable, str(ROOT / 'tools/levels/levels.py'), 'generate',
                '--output', str(generated / 'levels.zi')], cwd=ROOT, check=True)
