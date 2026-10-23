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
levels load from the current level file. External draft and campaign saves
appear within a second without reopening the editor. An active play session
keeps its board and recorded moves; a newer version waits until returning to
Edit, where the checks and undo history reset for that new board.
Reset restores the level's original reference board when available, including
every layer; Undo restores the edit you had before resetting.
The level overview checks the live signed server release in the background.
Purple means the current board matches it; pink means a local change needs an
update, and gray means the server could not be verified. Similarity stays green
below 50% and shifts smoothly toward red above 90%, including waiting levels.
Changed published boards show Update. Saved wins are reused only when they
still win on the visible draft; otherwise Update starts a check and shows
Checking. It keeps an already running check and publishes that exact draft
after the engine verifies its win. Diff shows the server board above your draft,
counts changed cells and highlights their objects, floor or decoration changes.
Update all force-publishes the already approved campaign without checking or
searching drafts again. Changed drafts and pending approvals stay intact.
Update buttons keep their action labels. A single publication status belongs to
the selected board; another level can queue while a campaign is being checked.
Repeated requests for the same board coalesce. One worker builds the contiguous
approved campaign, preserving requests that arrive during a build. Idle worker
locks turn interrupted work into a retryable failure instead of a permanent
busy state. `python3 scripts/publication_queue.py` lists the current queue;
`--json` includes exact boards, attempts, failed steps and bounded event history.
The queue never approves a draft or bypasses a release check.
The solution status appears once beside the controls while actions run. Completed
checks are remembered for the exact board and solver version; edits or a newer
solver invalidate that result. Fix it appears only after a failed check.
Completed runs are kept as bounded examples per level. Edits first reuse a
working example, then continue from full or partial recorded routes before
starting a fresh search. The solver combines breadth-first search, goal chains
and weighted macro searches. Its path guidance accounts for room geometry,
spare crates and doors that can open. A bounded first search concentrates on
objective routes and penalizes unrelated crate pushes; a fresh search with an
unbounded frontier follows when needed. Spare crates remain legal to move.
Legal moves and final wins still come
from the game engine. The macro and domain-guidance approach follows the
[Sokoban search research](https://www.ijcai.org/Proceedings/99-1/Papers/082.pdf).
Objects cannot enter the abyss or replace it with floor. Cached wins are replayed under the current rules
before being reused; this does not start a fresh search.

**Fix it** asks the configured GLM provider to repair an unwinnable board with
small changes. It can open pushing space or reposition existing pieces and
blocking decoration, while keeping objectives and the player and home. A repair
is applied only after a winning route passes the game engine; Undo restores the
previous draft. Failed proposals leave the board intact.

**GLM** has three actions. **Modify** creates a different layout with a similar
strategic winning route and the same puzzle inventory. **Redesign** makes a new
level, including its layout, pieces, start and home. **Prettify** changes ordinary
floor and wall appearances and adds non-blocking scenery, preserving every
object, mossy wall, button and other mechanic. It keeps the existing winning
route. Modify and Redesign must win in the game engine before being applied.
Prettify can also dress an unfinished draft without a new solution search;
both the worker and editor enforce equivalent terrain and non-blocking scenery,
and a known winning route is replayed. Scenery alone never counts as a win or approval.
Undo restores the previous board, and failed proposals leave it intact.
Redesigns are compared against verified wins for objectives, pushes and used
mechanics. Redesign first replays a winning route to identify each piece's
pushes, paint consumption, button presses, gate passages and objective order.
GLM uses that replay to plan more involved dependencies and a coherent visual
theme before it generates the new board. It proposes small changes for the
push sequence, room structure and scenery in separate steps; each step must
win before it becomes the next step's input. Engine feedback guides retries.
The previous level provides brief
context for pacing and visual contrast. The engine rejects easier proposals,
near copies of either level (including mirrored layouts and cosmetic color
changes), and boards without non-blocking scenery. An accepted redesign keeps
the source's objective, push and used-mechanic counts and adds an objective,
an actually used mechanic, or at least 10% more checked pushes (at least two).
These are checks on verified routes, not a proof of minimum solution length.
Empty walking and slow search do not count as puzzle difficulty.
**Approve** publishes in the background. It is disabled when that approval is
already published, and becomes available again if its update fails. A later
unproven draft does not prevent approving the last saved winning layout.
New levels require Approve before their first publication. Saved edits to levels
already on the server publish automatically once their winning route is proven.
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

## Downloads

Arcade supplies the standalone native hosts. Build the release APK with
`make -C ../arcade android-shovey-release`, then run:

    python3 scripts/android-release.py sign ../arcade/build/shovey-unsigned.apk --version VERSION

The signer checks the production package, version, release certificate, alignment,
both ARM architectures and the embedded collection digest. The release key and
password remain in ignored `backup/android-signing/`, and in the repository's
`SHOVEY_ANDROID_KEYSTORE` and `SHOVEY_ANDROID_KEYSTORE_PASSWORD` secrets;
preserve them for future updates. Only the public certificate belongs in Git.
`make -C ../arcade shovey-linux-download` packs the Linux download.

The Downloads workflow builds Arcade's host against each pushed commit. It signs
and checks the APK, plays the unpacked Linux download on a private display, and
keeps them on the draft release of the version Arcade's ledger names. Dispatch
the workflow with `publish` to publish that draft; a published version is never
replaced.
