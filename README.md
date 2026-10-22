# Shovey

![Shovey public hero](docs/screenshots/hero.png)

**Shovey** is a calm, fully playable push-puzzle game: read the courtyard,
plan the chain, send Shovey home, and keep the whole route in your head. It
is built for touch and keyboard, saves every unlocked puzzle, and proves
every shipped level by replaying it through the real game rules.

[![Shovey Classic](docs/screenshots/classic.png)](docs/screenshots/classic.png)
[![Shovey Editor](docs/screenshots/editor.png)](docs/screenshots/editor.png)
[![Shovey Island coming soon](docs/screenshots/island-coming-soon.png)](docs/screenshots/island-coming-soon.png)

## Play

- **Shovey Classic**: 157 stone-courtyard puzzles and a finale. Push balls
  into matching holes, crates onto corners, coloured blocks onto marks,
  collect keys and powers, then walk home.
- **Shovey Editor**: paint, test and share your own Classic boards. The
  built-in solver keeps checking while you build, and a level only counts
  after the engine replays a winning route.
- **Shovey Island**: coming soon. The entry is visible but disabled while
  the islands are being perfected.

Each edition keeps its own progress. Finishing a puzzle unlocks the next one
and starts it automatically; any unlocked puzzle can be replayed from its
first move.

Shovey runs inside [Arcade](https://github.com/waozixyz/arcade), alone as the
Shovey desktop app, and inside other hosts of the shared Apps interface.

Build the browser edition with `make web`; `make web-itch` is the same upload
directory for itch.io. Both build `build/web/` with Shovey embedded and ready
to play, using the same game view and rules as the desktop edition. Browser
progress stays on that browser and survives reloading the page. The standalone
browser host currently has no sound effects.

## Levels

`levels/classic.json` and `levels/island.json` hold every board. Each one
comes with a stored solution, and the tests replay every solution through
the real game rules, so no puzzle can ship unsolvable. After editing a
board, solve and check it:

    make solver
    python3 tools/levels/levels.py generate
    python3 tools/levels/levels.py previews
    make test

To check the bottom navigation while Classic and Island's editor play run
inside Inner Breeze, build Arcade's collection from these sources, then run
`make inbe-ui-test INBE_BINARY=/path/to/inbe INBE_SOURCE=/path/to/inbe/source
ARCADE_BUNDLE=/path/to/arcade.zib`. It uses a private display and disposable profiles.

When the solver cannot finish a board, play it and keep your winning route:

    make play
    build/play/shovey-play LIST ROUTES

LIST names the boards, one `classic 12` or `island 40` per line; each win is
replayed from the start and saved under ROUTES.

## Level editor

**Shovey Editor** is the third game beside Shovey Classic and Shovey Island.
Choose Classic or Island, then open any story level or one of your own, or
start a new one. Tap or drag on the board to paint the chosen piece, pick
a piece up from the board, and undo a stroke at a time; Island's shores and
banks follow the sand, meadow and water you paint. A story level is never
changed: the first stroke on one makes your own copy. Every change is kept
in the editor's own records.

While you build, the solver in `src/solver/` (Ziran, with the
searches of `tools/solver/solver.c`) checks the board a little every frame,
and a winning route it finds counts once the engine replays it. Winning the
board yourself under Play proves it too. Proven levels can be copied as text
for the developer, and, where the host offers it, shared as public,
friends-only or private collections that others find by alias or public ID.

The developer brings exported or shared levels into the game:

    make import-tool
    build/levels/import-edits EXPORT.json

Every route is replayed through the engines first, and nothing is written
unless all of them win. A copy of a story level replaces that level;
`--append` adds every level after the story instead. The level code and
pictures are then generated again (`--no-generate` skips that).

The developer editor runs directly from the repository:

    make editor
    build/private-editor/shovey-level-editor

Its source is `tools/editor/editor.zi`. **Tiles** paints the floor; **Objects**
holds pieces, animals, flowers, tufts, pebbles and trees. Tiles remain underneath
objects. Right-click in Objects clears pieces and decoration together, while
Undo restores the whole stroke. The active tab and brush are highlighted, and
the palette scrolls with large icons. Existing boards and drafts remain readable.
Drafts save immediately, played wins remain proven after reopening, and saved
levels load from the current level file.

**GLM Modify** proposes small edits inspired by the open board and its existing
winning route. It keeps the puzzle's pieces, colors, terrain, start and home.
A variation is applied only after its solution wins in the game engine, and
Undo, Redo and Reset remain available. Unproven proposals leave the level intact.

Chickens, turtles and crabs wander over clear floor and block Shovey and pushed
pieces. Goldfish, koi and minnows stay still on water, with gentle
animated ripples. Trees also block movement. Red, green and orange portals join
cyan, purple and yellow; each color connects to matching portals. Pressure plates
lower mossy stone walls. A separate iron gate opens and closes when Shovey pushes
a lever. Stone, moss, slate, brick, sandstone and timber walls share the same
blocking rules. Sand has visible grains; every paint color shares the same silhouette.
Placing abyss clears objects and decoration above it. Adjacent abyss cells share
one opening with a recessed stone lip at its boundary. Falling spins and shrinks
Shovey into the opening. Teleporters have a recessed inward spiral.

The original-board comparison measures mirrored puzzle layouts and nearby piece
placements, ignoring cosmetic floors and color swaps. The level overview caches
these scores. Run `build/private-editor/shovey-level-editor --similarity` to print
them without opening a window. Tree proposals, the rabbit alternative and image
generation prompts are kept in `tools/pixel/proposals/`.

Classic's optional `tiles` and `decorations` rows are stored separately from
`cells`; existing level numbers and untouched records are retained. Private
reference boards and editor drafts stay in the ignored `backup/` folder.
The public editor above handles painting, checking and sharing.

## Art

Shovey Classic uses its own generated pixel art: 32 by 32 sprites shown four
times larger. Walls,
floor, pits and markings are drawn by `tools/pixel/pixel.py`; characters and
objects come from an image model through OpenRouter, asked for pixel art and
fitted to the grid (prompts and sizes in `tools/pixel/sprites.json`, kept
results in `tools/pixel/native/`). The original round green player is preserved
in `tools/pixel/native/player.png`; only its dark interior ring was removed by
a manual pixel edit. The card is composed from the sprites. In landscape,
houses and other fixed objects stay upright, while shores, directional markers
and player facings turn with the board.

    OPENROUTER_API_KEY=... python3 tools/pixel/pixel.py generate   # missing sprites only
    python3 tools/pixel/pixel.py build

Island's pictures and card are rendered from the Three.js models in
`tools/art/`. The player is copied from Classic's exact sprites after either
art build, including the Island editor marker. The Island card uses the same
player bitmap, and landscape facings turn it with the board:

    cd tools/art && npm ci && node render.mjs

Level pictures are drawn from either set with
`python3 tools/levels/levels.py previews`.

The editor's card is drawn from both sets by `make editor-card`
(`tools/pixel/editor_card.zi`, on a private display).

`assets/*/art.json` lists each picture with what it shows.

## License

BSD 3-Clause. See `LICENSE`.
