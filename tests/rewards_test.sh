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
echo 'Rewards: a claim waits for an account, is credited once and remembered'
