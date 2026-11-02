# Standalone Island build input

`shovey-island.zx` is the reviewed compiled Island game, included in every
standalone collection by `scripts/player.py collection`. Downloads and Google
Play use that same collection build. The packer requires its exact size and
SHA-256 from `packaging/island.json`; missing or different bytes fail the build.
No private source or publisher key belongs here.

The host makes `assets/paid/shovey-island.zx` available to the game only after
the account service confirms ownership. The catalog retains its external bundle path so
Apps cannot open the included game before the host's ownership gate.
`collection --web` can build a browser collection using protected delivery.

To update this input, build and review Island with `player.py island-package`,
then copy the matching compiled file here alongside its reviewed descriptor.
`SHOVEY_ISLAND_BUNDLE` can select another exact compiled input for local builds.
