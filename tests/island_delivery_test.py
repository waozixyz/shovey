#!/usr/bin/env python3
"""Run an explicit private Island bytecode fixture in the production public host.

The fixture supplies fake account and HTTP boundaries; no account, wallet,
purchase or live node is used. Frames use a private Xvfb display. Requires an
already built collection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import player
import build_artifacts

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bundle', type=Path, required=True)
args = parser.parse_args()
descriptor = json.loads((ROOT / 'packaging/island.json').read_text())
assert hashlib.file_digest(args.bundle.open('rb'), 'sha256').hexdigest() == descriptor['sha256']
assert args.bundle.stat().st_size == descriptor['bytes']
work = ROOT / 'work/island-delivery-test'
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=ROOT, check=True)
work.mkdir(parents=True, exist_ok=True)
shutil.rmtree(work / 'profile', ignore_errors=True)
source = '''#import "player_host"
#import "island_package"
#import "island_unlock"
#import "player_platform"
#import "apps/host"
#import "apps/catalog"
#import "kryon/Frame"
#import "kryon/Desktop"
#import "kryon/tree"
#import "kryon/session"
#import "kryon/geometry"
#import "kryon/http_transfer"
#import "kryon/app_files"
#import "std/net_http"
#import "std/file"
#import "std/c_string"
#import "std/date_time_linux"
#import "std/text_buffer"
#import "std/vec"
fixture_bytes: string;
fixture_answer: [1024]u8;
FixtureShop :: (request: string) -> string {
    out: Vec(u8)
    BuilderPrint(*out, "{\\"product\\":\\"shovey.island\\",\\"owner\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"status\\":\\"done\\",\\"grant\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\",\\"expires_at\\":%}", UnixNow() + 3600)
    text := BuilderFinish(out)
    unused CopyCString(text, fixture_answer[:])
    AppFileFree(text)
    return TextUntilNul(fixture_answer[:])
}
FixtureStart :: (transfer: *HttpTransfer, request: HttpRequest, output: []u8, timeout: s32) -> bool {
    if request.method != "GET" || output.count != fixture_bytes.count + 1 { return false }
    for byte, index: fixture_bytes { output[index] = byte }
    return true
}
FixturePoll :: (transfer: *HttpTransfer, status: *s32, length: *s64) -> s32 {
    status.* = 200; length.* = fixture_bytes.count; return 1
}
FixtureStop :: (transfer: *HttpTransfer) {}
#program_export
main :: () -> s32 {
    bytes, found := ReadEntireFile(BUNDLE)
    if !found { return 1 }
    fixture_bytes = bytes
    defer { AppFileFree(bytes) }
    if !OpenDesktopSized(480, 820) { return 12 }
    defer { CloseDesktop() }
    if !CollectionOpenShovey(COLLECTION, PROFILE) { return 2 }
    defer { unused CollectionClose() }
    collection_island_package.service = FixtureShop
    collection_island_package.start = FixtureStart
    collection_island_package.poll = FixturePoll
    collection_island_package.stop = FixtureStop
    CollectionPackageAccount()
    entry := CollectionIslandEntry()
    if entry == null { return 3 }
    root := AppHostActiveRuntime(*collection_host)
    packed: bool
    before := AppHostChildBundle(*collection_host, root, root.node, entry, *packed)
    if packed || before.found { return 11 }
    if !IslandPackageFetch(*collection_island_package, entry) { return 3 }
    if !IslandPackageBundle(*collection_island_package, entry).found { return 4 }
    collection_island.owned = true
    if !CollectionOpenGame(ISLAND_UNLOCK_APP) { return 5 }
    runtime := AppHostActiveRuntime(*collection_host)
    if runtime == null || TextUntilNul(runtime.node.identity.id[:]) != ISLAND_UNLOCK_APP { return 6 }
    session := SessionOpen()
    if !SessionValid(session) { return 7 }
    defer { SessionClose(session) }
    bounds := Rectangle.{0.0, 0.0, 480.0, 820.0}
    for frame: 1..3 {
        BeginDesktopFrame()
        if BeginFrame(session, cast(u64)frame, bounds) != FrameStatus.FrameOk { return 8 }
        if !CollectionFrame(session, bounds, 0, 0) { return 9 }
        if EndFrame(session) != FrameStatus.FrameOk { return 10 }
        if !EndDesktopFrame() { return 13 }
        CollectionCollect()
    }
    return 0
}
'''
source = source.replace('BUNDLE', json.dumps(str(args.bundle.resolve()))).replace(
    'COLLECTION', json.dumps(str(player.OUT))).replace('PROFILE', json.dumps(str(work / 'profile')))
fixture = work / 'island_delivery.zi'
fixture.write_text(source)
generated = work / 'c'
shutil.rmtree(generated, ignore_errors=True)
environment = player.environment()
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'GDK_DISPLAY'):
    environment.pop(key, None)
environment['YUE_DESKTOP_RECOVERY'] = '0'
environment['SDL_AUDIODRIVER'] = 'dummy'
player.run([player.ziran(), 'build', '--project', *player.lock(), '--target=c', '--define', 'PLATFORM_DESKTOP',
    '--module-path', work, '--entry', 'island_delivery:main', '-o', generated, fixture], cwd=ROOT, env=environment)
profile = build_artifacts.request('entity:native-profile', 'linux-x86_64-gnu', ziran=player.ziran())
renderer = build_artifacts.renderer(build_artifacts.request('kryon:renderer-desktop', 'linux-x86_64-gnu', ziran=player.ziran()))
sources = sorted(generated.rglob('*.c'))
player.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-ffunction-sections', '-fdata-sections',
    '-I' + str(player.toolchain() / 'include'),
    *['-iquote' + str(path) for path in sorted({generated, *(p.parent for p in sources)})],
    *renderer['compile_flags'], *['-I' + path for path in renderer['include_directories']],
    *sources, '-Wl,--gc-sections', *build_artifacts.renderer_link(renderer),
    *profile.link_flags(include_archives=False), '-o', work / 'test'], cwd=ROOT, env=environment)
player.run(['xvfb-run', '-a', '-n', '400', '-s', '-screen 0 480x820x24', work / 'test'], cwd=ROOT, env=environment)
print('Private Island compiled package: exact public descriptor digest, protected client fixture, production host identity/open and three private display frames passed')
