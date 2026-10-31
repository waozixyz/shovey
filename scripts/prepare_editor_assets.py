"""Generate Classic's board previews in the editor's declared asset namespace."""
from pathlib import Path
import sys
from prepare_assets import prepare

if len(sys.argv) != 3:
    raise SystemExit('Usage: prepare_editor_assets.py ASSETS GENERATED_MODULES')
prepare(Path(sys.argv[1]).resolve() / 'classic', Path(sys.argv[2]).resolve())
