#!/bin/sh
set -eu
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER GDK_DISPLAY
export YUE_DESKTOP_RECOVERY=0
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
flags=--locked
if [ -f ziran.local.toml ]; then flags=; fi
# An explicit canonical upstream root permits focused contract tests before
# the coordinated package adoption, without changing this app's lock.
kryon=${1:-}
if [ -z "$kryon" ]; then kryon=$(./scripts/ziran.sh pkg path kryon $flags); fi
work="$root/work/chest-reminder-test"
git check-ignore -q "$work"
mkdir -p "$work"
./scripts/ziran.sh bundle --root "$root" \
    --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
    --entry chest_reminder_behavior:Check -o "$work/reminder.zx" "$root/tests/chest_reminder_behavior.zi"
result=$(./scripts/ziran.sh run "$work/reminder.zx")
test "$result" = 42 || { echo "Chest reminder local test failed: $result" >&2; exit 1; }
echo 'Chest reminder local policy tests: 19:00 default, game-open suppression, retained date state, duplicate guard, calendar changes, configured times and claim lower bound passed'
./scripts/ziran.sh build --target=c --exe --root "$root" \
    --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
    --entry chest_reminder_behavior:NativeCheck -o "$work/native" "$root/tests/chest_reminder_behavior.zi"
"$work/native/chest_reminder_behavior"
echo 'Chest reminder: native C policy and adapter local tests passed'
./scripts/ziran.sh bundle --root "$root" --define KRYON_HOSTED_UI \
    --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
    --bind-host chest_reminder_behavior \
    --entry chest_reminder_behavior:Check -o "$work/hosted.zx" "$root/tests/chest_reminder_behavior.zi"
result=$(./scripts/ziran.sh run "$work/hosted.zx")
test "$result" = 42 || { echo "Hosted chest reminder local test failed: $result" >&2; exit 1; }
echo 'Chest reminder: hosted public API forwarding, scoped identity and same rule replacement local tests passed'

apps=${2:-}
toolchain=${CHEST_REMINDER_TEST_TOOLCHAIN:-}
if [ -z "$apps" ]; then apps=$(./scripts/ziran.sh pkg path apps $flags); fi
if [ -z "$toolchain" ]; then toolchain=$(./scripts/ziran.sh pkg path ziran $flags); fi
./scripts/ziran.sh bundle --root "$root" \
    --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --module-path "apps=$apps/src" \
    --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
    --entry chest_reminder_host_behavior:Check -o "$work/host-policy.zx" "$root/tests/chest_reminder_host_behavior.zi"
result=$(./scripts/ziran.sh run "$work/host-policy.zx")
test "$result" = 42 || { echo "Chest reminder host policy local test failed: $result" >&2; exit 1; }
./scripts/ziran.sh build --target=c --exe --root "$root" \
    --module-path "$toolchain/std" --module-path "std=$toolchain/std" \
    --module-path "apps=$apps/src" \
    --module-path "kryon=$kryon/src/ui" --module-path "kryon=$kryon/src/backend" \
    --entry chest_reminder_host_behavior:NativeCheck -o "$work/host-native" "$root/tests/chest_reminder_host_behavior.zi"
"$work/host-native/chest_reminder_host_behavior"
echo 'Chest reminder host boundary: verified active Shovey slot, authority, foreground, Profile/Island exclusion passed in VM and native C'
