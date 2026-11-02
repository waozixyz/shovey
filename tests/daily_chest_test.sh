#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
set --
if [ ! -f ziran.local.toml ]; then set -- --locked; fi
toolchain=${DAILY_CHEST_TEST_TOOLCHAIN:-$(./scripts/ziran.sh pkg path ziran "$@")}
entity=${DAILY_CHEST_TEST_ENTITY:-$(./scripts/ziran.sh pkg path entity "$@")}
work="$root/work/daily-chest-test"
git check-ignore -q "$work"
mkdir -p "$work"
env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" bundle --root "$root" \
    --module-path "$toolchain/std" --module-path "std=$toolchain/std" --module-path "entity=$entity/src" \
    --bind controls:AppServiceHost=daily_chest_behavior:FakeService \
    --bind controls:AppRecordHost=daily_chest_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=daily_chest_behavior:FakeSave \
    --entry daily_chest_behavior:Check -o "$work/daily.zx" "$root/tests/daily_chest_behavior.zi"
result=$(env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" run "$work/daily.zx")
test "$result" = 42 || { echo "Daily chest local test failed: $result" >&2; exit 1; }
echo 'Daily chest: consecutive days, missed days, week wrap, restart, durable save failure and account isolation passed'
