# F-Droid

The recipe builds Shovey from source with `make android-fdroid`: Shovey's player (`scripts/player.py`) on Kryon's Android host, from this repository's own `ziran.lock`.

Every release publishes that build, signed, as `shovey-VERSION-fdroid.apk`, once F-Droid's own builder (`.github/workflows/fdroid.yml`) has reproduced it byte for byte. The canonical `.gitea/workflows/downloads.yml` publishes the verified downloads; the existing GitHub jobs retain their isolated signing key and only build/test artifacts. `Binaries` and `AllowedAPKSigningKeys` point F-Droid at the published APK.

Update the existing fdroiddata merge request only after the release tag and signed APK are public. Its single build must name that release's full source commit, version and Android version code. A newer `version.json` alone does not mean the release is available.

Keep the merge request in Draft until the inclusion review is complete.
