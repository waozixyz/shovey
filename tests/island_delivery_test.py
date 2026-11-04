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
import re
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
parser.add_argument('--bundled', action='store_true', help='verify included bytes unlock without transport')
parser.add_argument('--campaign', action='store_true', help='replay Island 1–30 through the compiled game (private source required)')
args = parser.parse_args()
descriptor = json.loads((ROOT / 'packaging/island.json').read_text())
assert hashlib.file_digest(args.bundle.open('rb'), 'sha256').hexdigest() == descriptor['sha256']
assert args.bundle.stat().st_size == descriptor['bytes']
work = ROOT / ('work/island-campaign-delivery-test' if args.campaign else 'work/island-delivery-test')
subprocess.run(['git', 'check-ignore', '-q', str(work)], cwd=ROOT, check=True)
work.mkdir(parents=True, exist_ok=True)
(work / 'scratch').mkdir(exist_ok=True)
os.environ['TMPDIR'] = str(work / 'scratch')
shutil.rmtree(work / 'profile', ignore_errors=True)
source = '''#import "player_host"
#import "island_package"
#import "entity/game_shop_native"
#import "entity/game_shop"
#import "std/json_scan"
#import "island_unlock"
#import "player_platform"
#import "apps/host"
#import "apps/tree"
#import "apps/catalog"
#import "apps/protocol"
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
#import "std/timer_linux"
#import "std/text_buffer"
#import "std/vec"
fixture_api :: #system_library "c";
IslandIdentityProbe :: () -> s32 #foreign fixture_api "IslandIdentityProbe";
fixture_bytes: string;
fixture_owned: bool;
// The owner's Island entitlement as Entity restores it from the node's
// ledger: a real-like page holding the signed Island unlock receipt.
fixture_entitled: bool;
FIXTURE_LEDGER :: "{\\"events\\":[{\\"receipt_id\\":\\"fixture-7\\",\\"issuer_id\\":\\"waozi\\",\\"asset_id\\":\\"waozi:token\\",\\"account_id\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"event_type\\":\\"credit\\",\\"amount_delta\\":100000000,\\"ledger_seq\\":7,\\"previous_hash\\":\\"0000000000000000000000000000000000000000000000000000000000000000\\",\\"event_hash\\":\\"1111111111111111111111111111111111111111111111111111111111111111\\",\\"created_at\\":\\"2026-11-03T12:00:00Z\\",\\"source_type\\":\\"monero\\",\\"source_ref\\":\\"fixture-deposit\\",\\"signature\\":\\"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\\"},{\\"receipt_id\\":\\"fixture-9\\",\\"issuer_id\\":\\"waozi\\",\\"asset_id\\":\\"waozi:token\\",\\"account_id\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"app_id\\":\\"shovey\\",\\"event_type\\":\\"debit\\",\\"amount_delta\\":-51000000,\\"ledger_seq\\":9,\\"previous_hash\\":\\"0000000000000000000000000000000000000000000000000000000000000000\\",\\"event_hash\\":\\"1111111111111111111111111111111111111111111111111111111111111111\\",\\"created_at\\":\\"2026-11-03T12:00:00Z\\",\\"source_type\\":\\"unlock\\",\\"source_ref\\":\\"shovey.island\\",\\"signature\\":\\"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\\"}]}";
FIXTURE_LEGACY :: "{\\"events\\":[{\\"receipt_id\\":\\"fixture-4\\",\\"issuer_id\\":\\"waozi\\",\\"asset_id\\":\\"waozi:token\\",\\"account_id\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"app_id\\":\\"entity\\",\\"event_type\\":\\"debit\\",\\"amount_delta\\":-85000000,\\"ledger_seq\\":4,\\"previous_hash\\":\\"0000000000000000000000000000000000000000000000000000000000000000\\",\\"event_hash\\":\\"1111111111111111111111111111111111111111111111111111111111111111\\",\\"created_at\\":\\"2026-11-03T12:00:00Z\\",\\"source_type\\":\\"unlock\\",\\"source_ref\\":\\"shovey.island\\",\\"signature\\":\\"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\\"}]}";
fixture_transfers: s32;
fixture_grants: s32;
fixture_answer: [1024]u8;
FixtureShop :: (request: string) -> string {
    if request == "status" {
        unused CopyCString(ifx fixture_owned then "{\\"owner\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"island_owned\\":true,\\"connected\\":true}" else "{\\"owner\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"island_owned\\":false,\\"connected\\":true}", fixture_answer[:])
        return TextUntilNul(fixture_answer[:])
    }
    if request == "shovey.island.grant" { fixture_grants += 1 }
    out: Vec(u8)
    BuilderPrint(*out, "{\\"product\\":\\"shovey.island\\",\\"owner\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"status\\":\\"done\\",\\"grant\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\",\\"expires_at\\":%}", UnixNow() + 3600)
    text := BuilderFinish(out)
    unused CopyCString(text, fixture_answer[:])
    AppFileFree(text)
    return TextUntilNul(fixture_answer[:])
}
FixtureStart :: (transfer: *HttpTransfer, request: HttpRequest, output: []u8, timeout: s32) -> bool {
    fixture_transfers += 1
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
    if IslandIdentityProbe() != 1 { return 17 }
    // Entity's restore reads Island's unlock receipt from a node ledger page,
    // at the launch price or from the legacy Profile app, only for its owner.
    restore: GameShopRestore
    if GameShopRestorePage(FIXTURE_LEDGER, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", *restore) != 0 || restore.cursor != 9 { return 38 }
    fixture_entitled = (restore.owned & (1 << SHOVEY_ISLAND_PRODUCT)) != 0
    if !fixture_entitled { return 38 }
    legacy: GameShopRestore
    if GameShopRestorePage(FIXTURE_LEGACY, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", *legacy) != 0 || (legacy.owned & (1 << SHOVEY_ISLAND_PRODUCT)) == 0 { return 39 }
    other: GameShopRestore
    if GameShopRestorePage(FIXTURE_LEDGER, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", *other) != 0 || (other.owned & (1 << SHOVEY_ISLAND_PRODUCT)) != 0 { return 39 }
    collection_island_package.service = FixtureShop
    collection_island_package.start = FixtureStart
    collection_island_package.poll = FixturePoll
    collection_island_package.stop = FixtureStop
    if BUNDLED && !collection_island_package.included.found { return 15 }
    // The paid bytes in the root must not consume Classic's existing working
    // allowance. Exercise the real host identity/digest/open path while the
    // account is unowned, before ever opening Island.
    if BUNDLED && collection_host.tree.byte_limit != APP_HOST_BYTE_LIMIT + bytes.count { return 19 }
    if BUNDLED {
        owner := AppHostActiveRuntime(*collection_host)
        classic_entry := AppCatalogAt(*owner.node.catalog, AppCatalogFind(*owner.node.catalog, "arcade.shovey"))
        if classic_entry == null { return 24 }
        limit := collection_host.tree.byte_limit
        charge := classic_entry.bytes + 65536 + cast(s64)size_of(AppNode)
        if charge > APP_HOST_BYTE_LIMIT - collection_host.tree.bytes {
            collection_host.tree.byte_limit = APP_HOST_BYTE_LIMIT
            rejected := AppHostPrepareChild(cast(*void)(*collection_host), owner.node, classic_entry, 0)
            collection_host.tree.byte_limit = limit
            if rejected != -1 { return 25 }
        }
    }
    if !CollectionOpenGame("arcade.shovey") { return 20 }
    classic := AppHostActiveRuntime(*collection_host)
    if classic == null || TextUntilNul(classic.node.identity.id[:]) != "arcade.shovey" { return 21 }
    if fixture_transfers != 0 || fixture_grants != 0 { return 22 }
    if !CollectionBack() { return 23 }
    CollectionCollect()
    CollectionPackageAccount()
    entry := CollectionIslandEntry()
    if entry == null || TextUntilNul(entry.cover.action[:]) != "buy" { return 3 }
    root := AppHostActiveRuntime(*collection_host)
    if BUNDLED {
        plan: AppInstallPlan
        if !AppHostInstallPlan(*collection_host, root.node, entry, *plan) || plan.count != 0 { return 18 }
        collection_island.owned = true
        CollectionIslandPump()
        if collection_island.owned || TextUntilNul(entry.cover.action[:]) != "buy" { return 16 }
    }
    packed: bool
    before := AppHostChildBundle(*collection_host, root, root.node, entry, *packed)
    if packed || before.found { return 11 }
    offer: AppsReply
    if !CollectionPackageFetch(null, "local", root.node, entry, APPS_INSTALL, *offer) ||
        offer.status != APPS_APPLIED || !collection_island_page ||
        IslandPackageBundle(*collection_island_package, entry).found { return 26 }
    collection_island_page = false
    fixture_owned = fixture_entitled
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
    if BUNDLED && (fixture_transfers != 0 || fixture_grants != 0) { return 14 }
    // Island opened as a game never shows the players' editor.
    if FixtureFind(session, 93303) { return 27 }
    if !CollectionBack() { return 28 }
    // The Editor's Island levels: only an owner is taken there; the title
    // opens Island in editor mode, and leaving Island reopens the Editor.
    if !CollectionOpenGame("arcade.shovey") || !CollectionActiveIs("arcade.shovey") { return 29 }
    editor := AppTreeQueueAddon(*collection_host.tree, collection_host.tree.active, SHOVEY_EDITOR_APP)
    if editor.status != APPS_QUEUED || !FixtureSettle(editor.request) || !CollectionActiveIs(SHOVEY_EDITOR_APP) { return 30 }
    collection_island.owned = false
    collection_island_editor = ISLAND_EDITOR_ASKED
    CollectionIslandEditorStep()
    if collection_island_editor != ISLAND_EDITOR_NONE || !CollectionActiveIs(SHOVEY_EDITOR_APP) { return 31 }
    collection_island.owned = true
    collection_island_editor = ISLAND_EDITOR_ASKED
    shown := false
    for frame: 4..400 {
        if !FixtureFrame(session, bounds, frame) { return 32 }
        // A new island, its Tiles with the cave floor and its Objects tab.
        if collection_island_editor == ISLAND_EDITOR_OPEN && CollectionActiveIs(ISLAND_UNLOCK_APP) && FixtureFind(session, 93303) &&
            FixtureFind(session, 93317) && FixtureFind(session, 93318) && FixtureFind(session, 94328) {
            shown = true
            break
        }
        unused SleepMilliseconds(5)
    }
    if !shown { return 33 }
    if !CollectionBack() { return 34 }
    back := false
    for frame: 401..800 {
        if !FixtureFrame(session, bounds, frame) { return 35 }
        if collection_island_editor == ISLAND_EDITOR_NONE && CollectionActiveIs(SHOVEY_EDITOR_APP) { back = true; break }
        unused SleepMilliseconds(5)
    }
    if !back { return 36 }
    // Back from Island is the Editor's start: Classic, and Island with no
    // Unlock tag while it is owned.
    if !FixtureEditorStart(session, bounds, 801, true) { return 37 }
    // Locked, the start's Island card carries Unlock and the price.
    fixture_owned = false
    collection_island.owned = false
    if !FixtureEditorStart(session, bounds, 1001, false) { return 40 }
    // The locked card opens the unlock page; once unlocked it goes straight
    // on to Island's editor, not the islands.
    CollectionIslandShow()
    collection_island_unlock_for_editor = true
    fixture_owned = fixture_entitled
    collection_island.owned = true
    unlocked := false
    for frame: 1201..1600 {
        if !FixtureFrame(session, bounds, frame) { return 41 }
        if collection_island_editor == ISLAND_EDITOR_OPEN && CollectionActiveIs(ISLAND_UNLOCK_APP) && FixtureFind(session, 93303) {
            unlocked = true
            break
        }
        unused SleepMilliseconds(5)
    }
    if !unlocked || collection_island_page { return 42 }
    return 0
}
// The Editor's start page: Classic's card and Island's, whose Unlock tag
// shows only while Island is locked.
FixtureEditorStart :: (session: Session, bounds: Rectangle, first: s64, owned: bool) -> bool {
    for frame: first..first + 199 {
        if !FixtureFrame(session, bounds, frame) { return false }
        if CollectionActiveIs(SHOVEY_EDITOR_APP) && FixtureFind(session, 110) && FixtureFind(session, 130) &&
            FixtureFind(session, 136) != owned { return true }
        unused SleepMilliseconds(5)
    }
    return false
}
FixtureFind :: (session: Session, key: u64) -> bool {
    for at: cast(s32)0..TreeCount(session) - 1 { if TreeNodeAt(session, at).key == key { return true } }
    return false
}
FixtureFrame :: (session: Session, bounds: Rectangle, frame: s64) -> bool {
    BeginDesktopFrame()
    if BeginFrame(session, cast(u64)frame, bounds) != FrameStatus.FrameOk { return false }
    if !CollectionFrame(session, bounds, 0, 0) { return false }
    if EndFrame(session) != FrameStatus.FrameOk { return false }
    if !EndDesktopFrame() { return false }
    CollectionCollect()
    return true
}
// Drains the apps host until request completes.
FixtureSettle :: (request: s64) -> bool {
    if !AppTreeDrain(*collection_host.tree) { return false }
    started := MonotonicMilliseconds()
    while CollectionPending(request) && MonotonicMilliseconds() - started < 60000 {
        unused SleepMilliseconds(5)
        if !AppTreeDrain(*collection_host.tree) { return false }
    }
    return !CollectionPending(request)
}
'''
source = source.replace('BUNDLED', 'true' if args.bundled else 'false')
if args.campaign:
    # Register only the independent rule modules: Island and Classic each have
    # a shared_campaign module, so registering the whole private folder would
    # collide with the production public host. These are disposable compiler
    # inputs; the engine/progress bodies and the shipped package stay unchanged.
    for name in ('island_engine', 'island_progress', 'island_kinds'):
        code = (ROOT / 'src/island' / (name + '.zi')).read_text()
        code = code.replace('#import, file "../island_levels.zi";', '#import "island_levels"')
        (work / (name + '.zi')).write_text(code)
    artwork = json.loads((ROOT / 'assets/shovey-island/art.json').read_text())
    paths = {'assets/shovey-island/' + item['path'] for item in artwork['files']}
    from island_campaign import shipped_levels
    paths = {path for path in paths if not (
        Path(path).parent.name in ('levels', 'levels-landscape') and
        Path(path).stem.isdecimal() and int(Path(path).stem) > shipped_levels())}
    for folder in ('tiles', 'player'):
        paths.update('assets/shovey-island/' + folder + '-landscape/' + path.name
                     for path in (ROOT / 'assets/shovey-island-landscape' / folder).glob('*.png'))
    values = '\n'.join(f'    if number == {index} {{ return {json.dumps(path)} }}'
                       for index, path in enumerate(sorted(paths)))
    (work / 'campaign_asset_paths.zi').write_text(
        f'CAMPAIGN_ASSET_COUNT :: {len(paths)}\n'
        f'CampaignAssetPath :: (number: s32) -> string {{\n{values}\n    return ""\n}}\n')
    source = '#import "island_campaign_delivery"\n' + source
    start = source.index('    // Island opened as a game never shows')
    end = source.index("// The Editor's start page")
    source = source[:start] + '    return ifx CampaignDelivered(session, bounds) then 0 else 43\n}\n' + source[end:]
if not args.bundled:
    source = source.replace('    CollectionPackageAccount()', '    collection_island_package.included = .{}\n    CollectionPackageAccount()', 1)
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
    '--module-path', work, '--module-path', ROOT / 'tests',
    '--entry', 'island_delivery:main', '-o', generated, fixture], cwd=ROOT, env=environment)
# Probe private provider state through the explicit native test host, without
# exporting account internals or changing dependency sources. No pump runs.
account_header = next(generated.rglob('*account_store.h'))
shop_header = next(generated.rglob('*game_shop_native.h'))
shop_answer = re.search(r'String (\w*EntityGameShopAnswer)\(', shop_header.read_text())[1]
(generated / 'identity_probe.c').write_text('''#include <string.h>
#include <stdio.h>
#include "ACCOUNT_HEADER"
#include "SHOP_HEADER"
static int owned_status(int expected) {
    String request = {(unsigned char *)"status", 6};
    String result = SHOP_ANSWER(request);
    char text[2048] = {0};
    if (result.length <= 0 || result.length >= sizeof(text)) return 0;
    memcpy(text, result.data, result.length);
    char owner[96];
    snprintf(owner, sizeof(owner), "\\"owner\\":\\"%s\\"", account_recovery.keys.public_id);
    return strstr(text, owner) != NULL && strstr(text, expected ? "\\"island_owned\\":true" : "\\"island_owned\\":false") != NULL;
}
int32_t IslandIdentityProbe(void) {
    memset(account_recovery.keys.public_id, 'a', 64);
    account_recovery.keys.public_id[64] = 0;
    owned_status(0);
    shop_owned = 1 << SHOVEY_ISLAND_PRODUCT;
    shop_loaded = true;
    if (!owned_status(1)) return 0;
    memset(account_recovery.keys.public_id, 'b', 64);
    if (!owned_status(0)) return 0;
    shop_owned = 1 << SHOVEY_ISLAND_PRODUCT;
    memset(account_recovery.keys.public_id, 0, sizeof(account_recovery.keys.public_id));
    return owned_status(0);
}
'''.replace('ACCOUNT_HEADER', account_header.name).replace('SHOP_HEADER', shop_header.name).replace('SHOP_ANSWER', shop_answer))
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
if args.campaign:
    print('Private-Xvfb Island campaign: first 30 compiled levels load and solve through real keys; '
          'every saved position matches its solution proof; portrait/landscape art and 12 locales present')
else:
    print('Private Island compiled package: exact public descriptor digest, protected client fixture, production host identity/open, '
          'three private display frames, a node-shaped Island receipt restored for its owner only, and the Editor\'s start: '
          'Island unlocked opens its editor with caves and objects, locked shows Unlock and unlocking goes straight on to it')
