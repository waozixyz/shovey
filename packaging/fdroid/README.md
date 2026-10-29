# F-Droid

The recipe builds Shovey from source with `make android-fdroid`: Shovey's player (`scripts/player.py`) on Kryon's Android host, from this repository's own `ziran.lock`.

Every release publishes that build, signed, as `shovey-VERSION-fdroid.apk`, once F-Droid's own builder (`.github/workflows/fdroid.yml`) has reproduced it byte for byte. `Binaries` and `AllowedAPKSigningKeys` point F-Droid at it.

Keep the merge request in Draft until the inclusion review is complete.
