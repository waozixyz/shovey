"""Prepare generated modules in the caller's directory without changing sources."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare(assets, generated):
    tool = str(ROOT / 'tools/levels/levels.py')
    subprocess.run([sys.executable, tool, 'generate', '--output', str(generated / 'levels.zi')], cwd=ROOT, check=True)
    subprocess.run([sys.executable, tool, 'previews', '--output', str(assets)], cwd=ROOT, check=True)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: prepare_assets.py ASSETS GENERATED_MODULES')
    prepare(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
