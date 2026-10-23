# Shovey

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
