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
Runtime bundle staging includes only the portrait atlas used by both board
orientations; loose source PNGs and the duplicate landscape atlas stay out
of downloads. The editor aliases Classic's atlas in the player collection.

Each of the 14 wall styles has 47 connection shapes: four cardinal joins
plus concave corners where the diagonal is open. Only exposed edges have
bevels. Both board rendering and level previews select these shapes from
neighbors; landscape computes the mask in screen directions. Timber uses
the plain generated wood texture, without metal bands. Ball sockets remain
transparent and are composed over a floor, including legacy one-layer maps
where the backing material is inferred from the neighboring floor.

`art/modern/before-after-board.png` renders the same approved level from the
preserved original art and the new art. `before-after-sprites.png` compares
tile families and character facings. The player/editor screenshots in that
folder are captured from fresh builds on private Xvfb displays.
`wall-spritesheets.png` shows all 47 shapes for every material, while
`wall-pit-laser-player.png` and `wall-pit-laser-landscape.png` capture a
private test board with wall junctions, a hollow ring, all six ball pits
and a reflected beam. `daily-chest-after.png` captures the simplified chest.

Game rules, cell IDs, level files, map formats and saved progress are unchanged.
