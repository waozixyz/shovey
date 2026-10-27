# Google Play testing

Shovey's Android ID is `xyz.waozi.shovey`. Its native Android host belongs to
Arcade; game source and store metadata belong here.

Build with `make -C ../arcade android-shovey-bundle`, Kryon's Google Play
edition: Profile sells Dew through Google Play Billing (`dew_100`, `dew_500`,
`dew_1000`, `dew_5000`). Sign and verify the result:

```sh
python3 scripts/android-release.py sign ../arcade/build/shovey-unsigned.aab \
  --version VERSION --output build/android/shovey-vVERSION-gplay.aab \
  --bundletool /path/to/bundletool.jar
```

The existing private Shovey release key is used by default. The verifier checks
Google's bundle format, package/version, both ARM architectures, target API 36,
the preserved release certificate, 16 KB native-library alignment, Play Billing
and the exact embedded game collection. The script never uploads.

GitHub releases to Google Play. After Downloads publishes a release it calls
the Google Play workflow (`play-bundle.yml`), which builds, signs and verifies
the Google Play edition, uploads it to the **internal testing** track with the
`GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` secret and creates or updates the Dew packs
with Entity's `tools/play_dew_products.py` (the node's Dew price plus 10%,
rounded up to a clean amount in each local currency).

Use `listing.json` and `fastlane/metadata/android` for the Console entry. Begin
with **Internal testing**; the owner selects the tester emails or Google Group.
Record the actual Play Console and opt-in URLs after creation. No production
rollout is configured. Preserve the existing signing key when enrolling in Play
App Signing so users can update across distribution channels.

Owner instruction, 2026-10-27: GitHub releases everything, so each published
release reaches internal testers without a separate upload step. No production
rollout is configured. Internal testing can begin before the full production listing is
complete; internal-only releases are exempt from the Data safety section.
Before closed/open testing or production, publish and verify the privacy-policy
URL and complete the listing, ads, target audience, content rating, Data safety
and account-deletion requirements. Local puzzles need no account;
optional Profile/account services contact the selected node and must be
represented accurately. Do not claim the whole app is network-free. Accept
Play terms only with owner authorization.

References: [create an app](https://support.google.com/googleplay/android-developer/answer/9859152),
[testing tracks](https://support.google.com/googleplay/android-developer/answer/9845334),
[target API](https://support.google.com/googleplay/android-developer/answer/11926878).

To upload one release again, run the Google Play workflow from its tag
(`--ref vVERSION`). It builds on the Arcade host pinned in that release unless
`arcade_revision` names another full Arcade commit whose Shovey ledger records
it. The tag is created by the release workflow; do not create or move tags
manually. This keeps game and host fixed while development continues on master.
