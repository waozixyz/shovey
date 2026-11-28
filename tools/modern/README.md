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

The later timber, sensor, paint and crate-goal refinements use four additional
provider PNG masters (`source/*-refined.png`), preserved in their original bytes.
The timber wall has darker inset boards and raised wooden braces. Sensors have open centers and separate bead phases, paint
uses one shared splat silhouette, and gold crate-target corners occupy 66% of
a cell with dark/light edging. The reference and previous sprite strip are
kept in `source/refinement-reference.png` and `source/refinement-before.png`.
The exact generation prompts are preserved in `source/refinement-prompts.json`;
`source/masters.json` records the delivered master hashes.
`art/modern/refinements-before-after.png` compares original, previous and
refined sprites; `target-floor-contrast.png` shows the target over every floor
material and four additional surfaces.

Grass, water and wooden floors use sixteen coordinate-selected cuts from
continuous 256px fields. Their opposite edges match exactly, and landscape
rotates each cut with the board. The delivered masters are preserved in
`source/grass-refined.png`, `source/water-refined.png` and
`source/wood-floor-refined.png`; prompts and hashes are recorded alongside
them. Legacy water animation names alias the same packed frame, so its
colour does not pulse. Player and skin artwork retain the previous design.
`art/modern/floors-tiling-before-after.png` compares all three materials;
`*-floor-spritesheet.png` shows each complete set.

Portal networks keep distinct coloured rims and spirals; the neutral blue
network has its own frame rather than aliasing the cyan network. The red
sensor bead is larger in every static and orbiting animation phase.
