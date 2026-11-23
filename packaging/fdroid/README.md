# F-Droid

The recipe builds Shovey from source with `make android-fdroid`: Shovey's player (`scripts/player.py`) on Kryon's Android host, from this repository's own `ziran.lock`.

Every release publishes that build, signed, as `shovey-VERSION-fdroid.apk`, on
the GitHub release, once F-Droid's own builder (`.github/workflows/fdroid.yml`)
has reproduced it byte for byte. Gitea's Downloads workflow builds and
publishes Shovey's own edition; GitHub's Downloads workflow builds the F-Droid
and Google Play editions and attaches them to the mirrored GitHub release,
where `Binaries` and `AllowedAPKSigningKeys` point F-Droid.

Update the existing fdroiddata merge request only after the release tag and signed APK are public. Its single build must name that release's full source commit, version and Android version code. A newer `version.json` alone does not mean the release is available.

Keep the merge request in Draft until the inclusion review is complete.
