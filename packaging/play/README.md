# Google Play testing

Shovey's Android ID is `xyz.waozi.shovey`. Its native Android host belongs to
Arcade; game source and store metadata belong here.

Build with `make -C ../arcade android-shovey-bundle`. Sign and verify the result:

```sh
python3 scripts/android-release.py sign ../arcade/build/shovey-unsigned.aab \
  --version VERSION --output build/android/shovey-VERSION.aab \
  --bundletool /path/to/bundletool.jar
```

The existing private Shovey release key is used by default. The verifier checks
Google's bundle format, package/version, both ARM architectures, target API 36,
the preserved release certificate, 16 KB native-library alignment and the exact
embedded game collection. It never uploads the result. The manual Play bundle
workflow builds and signs a candidate using existing repository signing secrets.

Use `listing.json` and `fastlane/metadata/android` for the Console entry. Begin
with **Internal testing**; the owner selects the tester emails or Google Group.
Record the actual Play Console and opt-in URLs after creation. No production
rollout is configured. Preserve the existing signing key when enrolling in Play
App Signing so users can update across distribution channels.

Approve the exact bundle and testing release before making it available to
testers. Internal testing can begin before the full production listing is
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

Run the manual workflow from an existing release tag (`--ref vVERSION`) and
provide a full `arcade_revision` whose Shovey ledger matches that release.
The tag is created by the release workflow; do not create or move tags manually.
This keeps game and host fixed while development continues on master.
