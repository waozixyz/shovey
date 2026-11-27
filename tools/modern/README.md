# Modern Classic artwork

The provider masters are preserved unchanged in `source/objects.png`,
`source/terrain.png` and `source/characters.png`. The original pre-redesign
449 sprites are preserved in `source/original.png`; `original.json` records
their rectangles, so the before/after pictures can always be rebuilt.

Rebuild with Python 3, Pillow, NumPy, SciPy and Matplotlib:

```sh
python3 tools/modern/build.py
python3 tools/levels/landscape.py
make -j1 previews
```

The build keeps all original sprite names and 128px source PNG paths. It
extracts complete connected silhouettes (including shapes crossing grid
boundaries), creates 64px runtime frames and deduplicates identical RGBA pixels across
both board orientations, character skins and animation phases. Each unique
frame has a one-pixel extruded border to prevent neighboring art bleeding
when scaled. A near-square grid leaves fewer than one row unused. Fixed
frame bounds preserve animation anchors, source crops and fall/portal meshes.

`assets/shovey/sprites/atlas.json` is the complete frame manifest.
`src/sprite_atlas_data.zi` is generated from it. Player and editor draw from
that single atlas through `src/sprite_atlas.zi`; individual named PNGs remain
available to editing tools and existing asset consumers.

`art/modern/before-after-board.png` renders the same approved level from the
preserved original art and the new art. `before-after-sprites.png` compares
tile families and character facings. The player/editor screenshots in that
folder are captured from fresh builds on private Xvfb displays.

Game rules, cell IDs, level files, map formats and saved progress are unchanged.
