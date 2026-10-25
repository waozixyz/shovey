#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
toolchain=${1:?usage: shared_progress_test.sh TOOLCHAIN}
entity=$(cd "$root" && "$toolchain/build/bin/ziran" pkg path entity)
work="$root/build/shared-progress-test"
mkdir -p "$work"
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" \
    --module-path "std=$toolchain/std" --module-path "entity=$entity/src" \
    --bind controls:AppServiceHost=shared_progress_behavior:FakeService \
    --bind controls:AppRecordHost=shared_progress_behavior:FakeRecord \
    --bind controls:SaveAppRecordHost=shared_progress_behavior:FakeSave \
    --entry shared_progress_behavior:Check -o "$work/progress.zx" "$root/tests/shared_progress_behavior.zi"
test "$("$toolchain/build/bin/ziran" run "$work/progress.zx")" = 42
"$toolchain/build/bin/ziran" bundle --root "$root" --module-path "$toolchain/std" \
    --module-path "std=$toolchain/std" --module-path "entity=$entity/src" \
    --entry island_shared_progress_behavior:Check -o "$work/island.zx" "$root/tests/island_shared_progress_behavior.zi"
test "$("$toolchain/build/bin/ziran" run "$work/island.zx")" = 42
echo 'Shared game progress: completion-only account writes, zero account calls during moves and active play, active Classic/Island boards preserved, account changes and offline fallback'
