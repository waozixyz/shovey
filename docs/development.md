# Shovey development

[Back to Shovey](../README.md).

Run the commands below from the repository root.

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

## Level editors

**Shovey Editor** opens from the game chooser alongside Shovey Classic.
Choose Classic or Island, then open an approved Classic story level or one of your own, or
start a new one. Island editing is available with no published story levels yet. Tap or drag on the board to paint the chosen piece, pick
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
holds pieces, animals, flowers, tufts, boulders and trees. Tiles remain underneath
objects. Right-click in Objects clears pieces and decoration together, while
Undo restores the whole stroke. The active tab and brush are highlighted, and
the palette scrolls with large icons. Existing boards and drafts remain readable.
Drafts save immediately, played wins remain proven after reopening, and saved
levels load from the current level file.
Reset restores the level's original reference board when available, including
every layer; Undo restores the edit you had before resetting.
The level overview checks the live signed server release in the background.
Purple means the current board matches it; pink means a local change needs an
update, and gray means the server could not be verified. Similarity stays green
below 50% and shifts smoothly toward red above 90%, including waiting levels.

**GLM Modify** designs a variation of the open board, using its existing winning
route as a reference. It can change the push sequence and find a new route;
engine-checked alternatives help when a proposal cannot be solved. It keeps the
puzzle's pieces, colors, terrain, start and home.
A variation is applied only after its solution wins in the game engine, and
Undo, Redo and Reset remain available. Unproven proposals leave the level intact.
**Approve** publishes in the background. It is disabled when that approval is
already published, and becomes available again if its update fails. A later
unproven draft does not prevent approving the last saved winning layout.
Saved edits to approved levels publish automatically once their winning route is proven.
Approved levels retain their purple mark while being edited.
Each gate color also has an open starting variant, which closes when its lever
is switched on. Mix both starting states for opposite passages on one lever.
All levers of one color share their state, so any matching lever toggles the passages.
Stone, slate, brick, sandstone and timber each have a mossy wall and a matching
colored pressure button. Buttons control only their matching wall type; an open
wall becomes its material's flat floor. Doors overlay the selected wall and open
that cell without adding their own wall frame.

Ducks, turtles and crabs choose independent directions from their first step,
wander over clear floor and block Shovey and pushed pieces. Goldfish, koi and
minnows also choose their own paths between water tiles with still sprites. Water has gentle
animated ripples. Trees also block movement. Red, green and orange portals join
cyan, purple and yellow; each color connects to matching portals. Pressure plates
lower mossy stone walls. A separate iron gate opens and closes when Shovey pushes
a matching lever; red, blue and green groups work independently. A wooden door opens when Shovey walks through it, with plain, red, blue and green variants. Floor lanterns and boulders block
Shovey and pushed pieces. Stone, moss, slate, brick, sandstone and timber walls share the same
blocking rules, with matching floors arranged before walls in the tile palette. Sand has visible grains; every paint color shares the same silhouette.
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
The integrated editor handles painting, checking and sharing.

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
