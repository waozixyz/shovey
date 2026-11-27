#!/bin/sh
# Dew rewards wait for an account, are claimed once and remembered.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
set --
if [ ! -f ziran.local.toml ]; then set -- --locked; fi
toolchain=${REWARDS_TEST_TOOLCHAIN:-$(./scripts/ziran.sh pkg path ziran "$@")}
work=${REWARDS_TEST_DIR:-"$root/work/rewards-test"}
git check-ignore -q "$work"
mkdir -p "$work"
env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" bundle --project "$@" --root "$root" \
    --bind controls:AppServiceHost=rewards_behavior:FakeService \
    --bind controls:AppRecordHost=rewards_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=rewards_behavior:FakeSave \
    --entry rewards_behavior:Check -o "$work/rewards.zx" "$root/tests/rewards_behavior.zi"
result=$(env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" run "$work/rewards.zx")
test "$result" = 42 || { echo "Rewards local test failed: $result" >&2; exit 1; }
echo 'Rewards: claims wait for an account; opened and claimed states survive restart, remote sync and stale device saves'
env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" bundle --project "$@" --root "$root" \
    --bind controls:AppServiceHost=rewards_sync_behavior:FakeService \
    --bind controls:AppRecordHost=rewards_sync_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=rewards_sync_behavior:FakeSave \
    --entry rewards_sync_behavior:Check -o "$work/sync.zx" "$root/tests/rewards_sync_behavior.zi"
result=$(env -u DISPLAY -u WAYLAND_DISPLAY "$toolchain/build/bin/ziran" run "$work/sync.zx")
test "$result" = 42 || { echo "Reward sync local test failed: $result" >&2; exit 1; }
echo 'Reward account sync: two devices, opened then claimed, stale saves, account isolation and unrelated campaign retention passed'
