#!/bin/sh
# Dew rewards wait for an account, are claimed once and remembered.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: rewards_test.sh TOOLCHAIN ENTITY}
entity=${2:?usage: rewards_test.sh TOOLCHAIN ENTITY}
work=${REWARDS_TEST_DIR:-"$root/build/rewards-test"}
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --module-path "entity=$entity/src" \
    --bind controls:AppServiceHost=rewards_behavior:FakeService \
    --bind controls:AppRecordHost=rewards_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=rewards_behavior:FakeSave \
    --entry rewards_behavior:Check -o "$work/rewards.zx" "$root/tests/rewards_behavior.zi"
test "$("$toolchain/build/bin/ziran" run "$work/rewards.zx")" = 42
echo 'Rewards: claims wait for an account; opened and claimed states survive restart, remote sync and stale device saves'
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --module-path "entity=$entity/src" \
    --bind controls:AppServiceHost=rewards_sync_behavior:FakeService \
    --bind controls:AppRecordHost=rewards_sync_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=rewards_sync_behavior:FakeSave \
    --entry rewards_sync_behavior:Check -o "$work/sync.zx" "$root/tests/rewards_sync_behavior.zi"
test "$("$toolchain/build/bin/ziran" run "$work/sync.zx")" = 42
echo 'Reward account sync: two devices, opened then claimed, stale saves, account isolation and unrelated campaign retention passed'
