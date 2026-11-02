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
work="$root/build/tests/world_map_progression_test"
mkdir -p "$work"
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
"$ziran" bundle --root "$root/tests" --module-path "$root/src" --module-path "entity=$entity/src" \
    --entry world_map_progression_test:Check -o "$work/progression.zx" "$root/tests/world_map_progression_test.zi"
result=$("$ziran" run "$work/progression.zx")
test "$result" = 0 || { echo "World map progression portable local test failed: $result" >&2; exit 1; }
"$ziran" build --target=c --exe --root "$root/tests" --module-path "$root/src" --module-path "entity=$entity/src" \
    --entry world_map_progression_test:Check -o "$work" "$root/tests/world_map_progression_test.zi"
"$work/world_map_progression_test"
echo 'World map progression local tests passed in portable VM and native C: 175 reachable boards, six OR forks, revisits without replay, legacy saves/account restore, detached discovered secrets'
