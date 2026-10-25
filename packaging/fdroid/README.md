# F-Droid

The recipe builds Shovey from source with `make android-fdroid`, using the Arcade host pinned in `packaging/android`. The level publisher pins the Arcade commit that records each release (`scripts/pin-android-host.py`).

Every release publishes that build, signed, as `shovey-VERSION-fdroid.apk`, once F-Droid's own builder (`.github/workflows/fdroid.yml`) has reproduced it byte for byte. `Binaries` and `AllowedAPKSigningKeys` point F-Droid at it.

Keep the merge request in Draft until the inclusion review is complete.
