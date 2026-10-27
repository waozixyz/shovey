# Shovey

## Google Play purchasing

Owner instruction, 2026-10-27, replacing the 2026-10-26 rule that disabled
Dew buying in Play builds: every app has a normal edition (no suffix), an
`-fdroid` and a `-gplay` edition. The Google Play edition sells the same Dew
through Google Play Billing, at 10% above the base price rounded up to a
clean amount in each local currency; the direct and F-Droid editions buy Dew
with Monero at dew.waozi.xyz. Arcade builds the Play bundle as Kryon's
`gplay` edition, so Entity's Profile Dew page lists the Play packs and credits
them after the node verifies each purchase. Keep Play Billing in Play builds
and offer no other way to buy Dew there. Earning Dew rewards is separate from
buying Dew. Store declarations must describe the actual Play build.

Owner instruction, 2026-10-27: GitHub releases everything. Every published
Shovey release goes to Google Play's internal testing track from the Downloads
workflow (`play-bundle.yml`), which also creates or updates the Dew packs. Do
not upload to Google Play from a session or a local machine; fix the workflow
instead.

## Web deployment

Owner instruction, 2026-10-22: the playable web game lives at
https://shovey.waozi.xyz on Cloudflare Pages, linked from https://waozi.xyz.
Do not deploy it to GitHub Pages or use a github.io play link.

Use the existing Cloudflare Pages deployment pattern in
`waozixyz/waozi/.github/workflows/pages.yml`. Shovey's GitHub Actions workflow
builds and tests the approved campaign, then deploys the `shovey` Pages
project from `master`. Keep the website's link in its source
`site/data/waozi.toml` pointing to the subdomain.

Verify the deployed revision and playable game at the actual custom domain.
Browser checks use a private headless browser or private display, never the
owner's live windows.

## Editor text

Treat owner feedback as work requests, not UI copy. Do not turn chat
instructions, release policies, approval boundaries or development reminders
into editor labels, banners or help text. Use short control labels and brief,
actionable status. Keep detailed explanations in development logs or
documentation.

## Reloading the developer editor

Owner instruction, 2026-10-22: when the owner asks to reload or reopen Shovey's
developer editor, close and relaunch that editor after backing up its drafts and
preserving the current level. Do not request repeat confirmation. This is the
owner's explicit exception to the parent rule to leave running applications
open. Keep every other application open.
