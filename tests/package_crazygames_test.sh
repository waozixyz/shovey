set -eu

root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
work="$root/work/package-crazygames-test"
source="$work/source"
output="$work/shovey-crazygames.zip"
revision=$(git -C "$root" rev-parse HEAD)

rm -rf "$work"
mkdir -p "$source"
cat >"$source/index.html" <<PAGE
<!doctype html><html><head><title>Shovey</title>
  <!-- Website metadata --><link rel=canonical href=https://shovey.waozi.xyz/>  <!-- End website metadata -->
</head><body><script>    <!-- Website-only runtime fallback -->var gameHome='https://shovey.waozi.xyz/';    <!-- End website-only runtime fallback -->
function gameFile(name) { return fileBase + name + '?v=' + buildRevision; }
      runtimeScript.onerror = function() {
        if (loadFromHome()) loadRuntime();
        else Module.setStatus('Could not download Shovey.');
      };
</script></body></html>
PAGE
for name in index.js index.wasm index.data title-landscape.jpg title-portrait.jpg logo.png icon-192.png manifest.webmanifest icon.png; do
  printf '%s' "$name" >"$source/$name"
done
printf '{"revision":"%s"}\n' "$revision" >"$source/build.json"

cd "$root"
ziran run --target=c scripts/package_crazygames.zi -- --source "$source" --output "$output"
listing=$(unzip -Z1 "$output")
expected='index.html
index.js
index.wasm
index.data
title-landscape.jpg
title-portrait.jpg
logo.png
icon-192.png
manifest.webmanifest
icon.png'
[ "$listing" = "$expected" ]
unzip -t "$output" | grep -q 'No errors detected'
page=$(unzip -p "$output" index.html)
! printf '%s' "$page" | grep -q 'https://'
! printf '%s' "$page" | grep -q 'gameHome'
! printf '%s' "$page" | grep -Eq 'fileBase|loadFromHome'
printf '%s' "$page" | grep -Fq "function gameFile(name) { return name + '?v=' + buildRevision; }"

printf '{"revision":"0000000000000000000000000000000000000000"}\n' >"$source/build.json"
if ziran run --target=c scripts/package_crazygames.zi -- --source "$source" --output "$output" >"$work/stale.log" 2>&1; then
  echo 'The stale web build was accepted' >&2
  exit 1
fi
grep -q 'The web build receipt names another revision' "$work/stale.log"

echo 'CrazyGames package fixture and provenance checks passed'
