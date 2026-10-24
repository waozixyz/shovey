#!/bin/sh
# The touch controls and sound choices survive a relaunch in every host.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: controls_test.sh TOOLCHAIN}
work="$root/build/controls-test"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --bind controls:AppServiceHost=controls_behavior:FakeService \
    --bind controls:AppRecordHost=controls_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=controls_behavior:FakeSave \
    --entry controls_behavior:Check -o "$work/controls.zx" "$root/tests/controls_behavior.zi"
test "$("$toolchain/build/bin/ziran" run "$work/controls.zx")" = 42
echo 'Controls: the movement choice and sound survive a relaunch, from records or Arcade services'
