#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
ziran=${ZIRAN:-./scripts/ziran.sh}
entity=
if [ -f ziran.local.toml ]; then
    entity=$(python3 -c 'import tomllib; print(tomllib.load(open("ziran.local.toml", "rb")).get("overrides", {}).get("entity", ""))')
fi
if [ -z "$entity" ]; then entity=$("$ziran" pkg path entity); fi
git check-ignore -q work/world-map-progression-test
work="$root/work/world-map-progression-test"
mkdir -p "$work/tmp" "$work/native-run"
export TMPDIR="$work/tmp" ZIRAN_NATIVE_DIR="$work/native-run"
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
"$ziran" bundle --root "$root/tests" --module-path "$root/src" --module-path "entity=$entity/src" \
    --entry world_map_progression_test:Check -o "$work/progression.zx" "$root/tests/world_map_progression_test.zi"
result=$("$ziran" run "$work/progression.zx")
test "$result" = 0 || { echo "World map progression portable local test failed: $result" >&2; exit 1; }
"$ziran" build --target=c --exe --root "$root/tests" --module-path "$root/src" --module-path "entity=$entity/src" \
    --entry world_map_progression_test:Check -o "$work" "$root/tests/world_map_progression_test.zi"
"$work/world_map_progression_test"
echo 'World map progression local tests passed through the portable ZX runner and native C: 175 stable boards, two painted A/B loops (arms 5/4 and 7/2), all 4 route choices, OR merges, old four-branch saves, completed replays, legacy saves/account restore, detached secrets 1001..1003'
