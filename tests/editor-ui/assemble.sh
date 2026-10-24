#!/bin/sh
# Disposable: a standalone Shovey player whose collection also holds the
# editor, built with Arcade's toolchain from the staged bundle inputs.
set -eu
shovey=/mnt/storage/Projects/waozixyz/shovey
arcade=/mnt/storage/Projects/waozixyz/arcade
ziran=/mnt/storage/Projects/ziranlang/ziran
kryon=/mnt/storage/Projects/kryonlabs/kryon
apps=/mnt/storage/Projects/waozixyz/apps
out=$shovey/build/ui-test
rm -rf "$out/collection" "$out/player"
mkdir -p "$out/collection/assets/apps" "$out/collection/assets/arcade/games" "$out/collection/assets/arcade/previews" "$out/player"
cp "$arcade/build/shovey-collection/assets/apps/apps.zx" "$out/collection/assets/apps/apps.zx"
children=""
for name in shovey shovey-island shovey-editor; do
    "$ziran/build/bin/zi2zx" bundle --root "$shovey" \
        --module-path "$shovey/build/game-generated/$name" \
        --module-path "$kryon/src/ui" --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
        --module-path "std=$ziran/std" --module-path "$ziran/std" --module-path "apps=$apps/src" \
        --define KRYON_HOSTED_UI --asset-dir "assets=$shovey/build/game-assets/$name/assets" \
        --entry "$(python3 -c "import json;print(json.load(open('$shovey/build/game-assets/$name/assets/$name/catalog.json'))['entry'])")" \
        -o "$out/collection/assets/arcade/games/$name.zx" \
        "$shovey/$(python3 -c "import json;print(json.load(open('$shovey/build/game-assets/$name/assets/$name/catalog.json'))['source'])")"
    cp "$shovey/build/games/$name-preview.png" "$out/collection/assets/arcade/previews/$name.png"
done
python3 - "$out" <<'PY'
import hashlib, json, sys
from pathlib import Path
out = Path(sys.argv[1])
children = []
for name, ident, title in [('shovey', 'arcade.shovey', 'Shovey Classic'), ('shovey-island', 'arcade.shovey-island', 'Shovey Island'),
                           ('shovey-editor', 'arcade.shovey-editor', 'Shovey Editor')]:
    bundle = out / f'collection/assets/arcade/games/{name}.zx'
    children.append(dict(id=ident, title=title, bundle=f'assets/arcade/games/{name}.zx', protocol='node/2',
                         expected_id=name, version='0.0.1', sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                         preview=f'assets/arcade/previews/{name}.png'))
catalog = dict(schema=1, id='arcade.shovey-player', title='Shovey', harness='assets/apps/apps.zx', children=children)
(out / 'collection/assets/apps/catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
(out / 'children.json').write_text(json.dumps(children))
PY
"$ziran/build/bin/zi2zx" bundle --root "$arcade/src" --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
    --module-path "$kryon/src/ui" --module-path "std=$ziran/std" --module-path "$ziran/std" \
    --entry shovey_collection:Main --asset-dir "assets=$out/collection/assets" -o "$out/player/shovey.zx" "$arcade/src/shovey_collection.zi"
python3 - "$out" <<'PY'
import hashlib, json, sys
from pathlib import Path
out = Path(sys.argv[1])
meta = dict(id='arcade.shovey-player', version='0.0.1',
            sha256=hashlib.sha256((out / 'player/shovey.zx').read_bytes()).hexdigest(),
            apps_sha256=hashlib.sha256((out / 'collection/assets/apps/apps.zx').read_bytes()).hexdigest(),
            children=json.loads((out / 'children.json').read_text()), source_mode='project')
(out / 'player/shovey.json').write_text(json.dumps(meta, indent=2) + '\n')
PY
cp "$arcade/build/shovey" "$out/player/shovey"
echo "assembled $out/player"
