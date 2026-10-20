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

- **Shovey Classic**: 155 stone-courtyard puzzles and a finale. Push balls
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
directory for itch.io. Both build `build/web/` from the same portable Shovey
bundle used by desktop hosts.

## Levels

`levels/classic.json` and `levels/island.json` hold every board. Each one
comes with a stored solution, and the tests replay every solution through
the real game rules, so no puzzle can ship unsolvable. After editing a
board, solve and check it:

    make solver
    python3 tools/levels/levels.py generate
    python3 tools/levels/levels.py previews
    make test

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

While you build, the solver in `apps/shovey/solver/` (Ziran, with the
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

The developer editor keeps level work private while the public editor above handles painting, checking and sharing.

## Art

Shovey Classic uses its own generated pixel art: 32 by 32 sprites shown four
times larger. Walls,
floor, pits and markings are drawn by `tools/pixel/pixel.py`; characters and
objects come from an image model through OpenRouter, asked for pixel art and
fitted to the grid (prompts and sizes in `tools/pixel/sprites.json`, kept
results in `tools/pixel/native/`). The card is composed from the sprites.

    OPENROUTER_API_KEY=... python3 tools/pixel/pixel.py generate   # missing sprites only
    python3 tools/pixel/pixel.py build

Island's pictures and card are rendered from the Three.js models in
`tools/art/`:

    cd tools/art && npm ci && node render.mjs

Level pictures are drawn from either set with
`python3 tools/levels/levels.py previews`.

The editor's card is drawn from both sets by `make editor-card`
(`tools/pixel/editor_card.zi`, on a private display).

`assets/*/art.json` lists each picture with what it shows.

## License

BSD 3-Clause. See `LICENSE`.
