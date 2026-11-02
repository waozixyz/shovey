#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
ziran=${ZIRAN:-./scripts/ziran.sh}
lock=--locked
if [ -f ziran.local.toml ]; then lock=; fi
if [ -f ziran.local.toml ]; then
    kryon=$(python3 -c 'import tomllib; print(tomllib.load(open("ziran.local.toml", "rb")).get("overrides", {}).get("kryon", ""))')
    if [ -z "$kryon" ]; then kryon=$($ziran pkg path kryon); fi
else
    kryon=$($ziran pkg path kryon $lock)
fi
"$ziran" build --target=c --exe --root tests --module-path "kryon=$kryon/src/ui" --module-path "$kryon/src/ui" --entry world_map_layout_test:main -o build/tests/world_map_layout_test tests/world_map_layout_test.zi
env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS -u SESSION_MANAGER -u GDK_DISPLAY build/tests/world_map_layout_test/world_map_layout_test
