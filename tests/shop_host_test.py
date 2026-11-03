#!/usr/bin/env python3
"""Run the host's production navigation functions with a fake Apps boundary.

No account, network, input, display or purchasing service is involved.
"""
from pathlib import Path
import re
import importlib.util
import sys
import subprocess
import tempfile
from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT / 'work/shop-host-test'
subprocess.run(['git', 'check-ignore', '-q', str(WORK_ROOT)], cwd=ROOT, check=True)
WORK_ROOT.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix='run-', dir=WORK_ROOT))

def function(path, name):
    text = path.read_text()
    start = re.search(r'^' + name + r' ::', text, re.M).start()
    end = re.search(r'^\w+ ::', text[start + len(name) + 3:], re.M)
    return text[start:start + len(name) + 3 + end.start()] if end else text[start:]

source = '''#import "std/vec"
#import "std/c_string"
#import "std/text_buffer"
ProductionShopUI :: #import "shop_view";
ReferralLink :: #import "entity/referral_model";
Identity :: struct { id: [128]u8 }
AppLocation :: struct { id: [128]u8; sha256: [65]u8 }
AppLocator :: struct { identity: Identity; chain: Vec(AppLocation) }
Entry :: struct { id: [128]u8; sha256: [65]u8 }
AppNode :: struct { identity: Identity; collection: bool; catalog: s32 }
Tree :: struct { active: s32; account_epoch: s64 }
Host :: struct { tree: Tree }
Runtime :: struct { node: *AppNode }
CollectionRecords :: struct { files: s32 }
collection_host: Host;
collection_shop_request: string;
collection_shop_locator: AppLocator;
root: AppNode;
leaf: AppNode;
entry: Entry;
runtime: Runtime;
records: CollectionRecords;
verified: s32;
exists: bool = true;
routed: bool = true;
writable: bool = true;
writes: s32;
route_calls: s32;
backs: s32;
written: string;
AppTreeNode :: (tree: *Tree, active: s32) -> *AppNode { return *root }
AppCatalogFind :: (catalog: *s32, id: string) -> s64 { return ifx exists && id == "arcade.shovey" then 0 else -1 }
AppCatalogAt :: (catalog: *s32, at: s64) -> *Entry { return ifx at == 0 then *entry else null }
AppTreeLocate :: (tree: *Tree, active: s32, locator: *AppLocator) -> bool {
    locator.identity = root.identity
    return VecPush(locator.chain, AppLocation.{.id = root.identity.id})
}
AppLocatorClear :: (locator: *AppLocator) { VecFree(locator.chain); locator.identity = .{} }
AppHostOpenLocator :: (host: *Host, locator: *AppLocator) -> s32 {
    if locator.chain.count != 2 || TextUntilNul(locator.identity.id[:]) != "arcade.shovey" ||
        TextUntilNul(locator.chain[1].sha256[:]) != "verified-catalog-digest" { return -1 }
    return verified
}
AppHostRoute :: (host: *Host) -> bool { route_calls += 1; return routed }
AppHostActiveRuntime :: (host: *Host) -> *Runtime { return *runtime }
CollectionRecordsFor :: (id: string) -> *CollectionRecords { return ifx id == "arcade.shovey" then *records else null }
AppFileWrite :: (files: *s32, name: string, value: string) -> bool {
    if name != "shop.request" || (value != "shop" && value != "chest") { return false }
    writes += 1; written = value
    return writable
}
AppHostBack :: (host: *Host) -> s32 { backs += 1; return 1 }
'''
source += r'''
ShopUI :: #import "shop_fake";
Book :: #import "book_fake";
#import "kryon/geometry"
UiFrame :: struct { session: s32; top: s32; bottom: s32; width: s32; height: s32; now: float64 }
APP_IDENTIFY :: 1;
APP_FRAME :: 2;
APP_PROTOCOL :: 1;
web_covers_open: bool = true;
web_editor_open: bool;
is_mini: bool;
wall: float64 = 1728000000.0;
today_seen: s64;
key: s32;
covers: s32;
editor_frames: s32;
game_frames: s32;
shop_frames: s32;
AppMode :: () -> s32 { return APP_FRAME }
AppNow :: () -> float64 { return wall }
AppMini :: () -> bool { return is_mini }
CanvasSetExitKey :: (key: s32) {}
AppIdentity :: (id: string) {}
AppDescribe :: (title: string, icon: string) {}
ShoveyShopSetToday :: (today: s64) { today_seen = today }
ReadAppUiHost :: () -> UiFrame { return UiFrame.{.width = 320, .height = 640, .now = 17.0} }
AppKeyHost :: () -> s32 { return key }
ShoveyShopBack :: () -> bool { ShopUI.open = false; return true }
ShoveyShopFrame :: (session: s32, area: Rectangle, now: float64, today: s64) -> bool { shop_frames += 1; return true }
WebCovers :: () { covers += 1 }
EditorFrame :: (locale: string) { editor_frames += 1 }
ShoveyFrame :: () { game_frames += 1 }
'''
source += r'''
entity_ready: bool;
entity_visible: bool;
entity_heading: string;
entity_save: bool = true;
entity_route: bool = true;
entity_back: bool;
profile_calls: s32;
referral_calls: s32;
referral_code: [129]u8;
EntityHostSave :: () -> bool { return entity_save }
EntityHostProfileRequest :: (page: string) -> bool { profile_calls += 1; return entity_route }
EntityHostReferrals :: (code: string) -> bool {
    referral_calls += 1
    return CopyCString(code, referral_code[:]) && entity_route
}
EntityHostBack :: () -> bool { return entity_back }
'''
source += r'''
production_route: string;
production_navigation_backs: s32;
#program_export
AppServiceHost :: (name: string, request: string) -> string {
    if name == "arcade.navigation" && request == "back" { production_navigation_backs += 1; return "queued" }
    return ""
}
#program_export
AppRecordHost :: (name: string) -> string { return ifx name == "shop.request" then production_route else "" }
#program_export
SaveAppRecordHost :: (name: string, text: string) -> bool {
    if name != "shop.request" { return false }
    production_route = text
    return true
}
#program_export
AppSupportsHost :: (name: string) -> bool { return false }
#program_export
AppLocaleHost :: (key: string) -> string { return key }
'''
for name in ('EntityShowPage', 'EntityBack'):
    source += function(ROOT / 'src/player_entity.zi', name) + '\n'
source += function(ROOT / 'src/web/game.zi', 'Main').replace('Main ::', 'WebMain ::', 1) + '\n'
(WORK / 'shop_fake.zi').write_text('''open: bool;
pumps: s32;
day: s64;
Pump :: (now: float64, today: s64) { pumps += 1; day = today }
IsOpen :: () -> bool { return open }
''')
(WORK / 'book_fake.zi').write_text('''open: bool;
#import "kryon/geometry"
BookCoverAction :: (session: s32, key: u64, bounds: Rectangle) -> bool { return false }
BookOpen :: () { open = true }
BookIsOpen :: () -> bool { return open }
BookBack :: () -> bool {
    was_open := open
    open = false
    return was_open
}
BookFrame :: (session: s32, bounds: Rectangle, fallback_owner: string) -> bool { return open }
''')
source += r'''
Package :: struct { owner: [65]u8 }
Unlock :: struct { owned: bool }
collection_island_package: Package;
collection_island_account: [65]u8;
collection_island_blocked: bool;
collection_island: Unlock;
collection_island_poll: float64;
ISLAND_UNLOCK_APP :: "arcade.shovey-island";
APPS_BACK :: 3;
AppsRequest :: struct { operation: s32 }
save_ok: bool;
cancel_child: s32;
cancel_locator: s32;
forced_back: s32;
shop_calls: s32;
dew_calls: s32;
IslandPackagePump :: (package: *Package) {}
AppHostCancelChild :: (host: *Host) { cancel_child += 1 }
AppHostCancelLocator :: (host: *Host) { cancel_locator += 1 }
AppTreeQueue :: (tree: *Tree, active: s32, request: AppsRequest) -> s32 { forced_back += 1; return 1 }
AppTreeDrain :: (tree: *Tree) -> bool { if save_ok { runtime.node = *root }; return save_ok }
EntityGameShopAnswer :: (request: string) -> string { shop_calls += 1; return request }
EntityDewAnswer :: (request: string) -> string { dew_calls += 1; return request }
kept_epoch: s64 = -1;
CollectionKeepLocalNodes :: (previous: s64) { kept_epoch = previous }
'''
for name in ('CollectionPackageAccount', 'CollectionShopAnswer', 'CollectionDewAnswer', 'CollectionShopQueue', 'CollectionShopNavigate', 'CollectionLocaleLabel'):
    source += function(ROOT / 'src/player_host.zi', name) + '\n'
source += r'''
#program_export
Check :: () -> s32 {
    if CollectionShopAnswer("shovey.island.grant") != "" || CollectionShopAnswer("shovey.island.grant.status") != "" ||
        CollectionDewAnswer("shop:shovey.island.grant") != "" || CollectionDewAnswer("shop:shovey.island.grant.status") != "" ||
        shop_calls != 0 || dew_calls != 0 { return 40 }
    if CollectionDewAnswer("balance") != "balance" || CollectionDewAnswer("shop:status") != "status" ||
        shop_calls != 1 || dew_calls != 1 { return 41 }
    unused CopyCString(ISLAND_UNLOCK_APP, leaf.identity.id[:])
    runtime.node = *leaf
    unused CopyCString("old-owner", collection_island_account[:])
    // Sync already happened in another callback; durable host snapshot catches it.
    unused CopyCString("new-owner", collection_island_package.owner[:])
    CollectionPackageAccount()
    // The title and Editor keep the previous epoch's navigation under "local".
    if !collection_island_blocked || forced_back != 1 || collection_host.tree.account_epoch != 1 ||
        cancel_child != 1 || cancel_locator != 1 || kept_epoch != 0 { return 43 }
    CollectionPackageAccount()
    if !collection_island_blocked || forced_back != 2 || collection_host.tree.account_epoch != 1 { return 44 }
    save_ok = true
    CollectionPackageAccount()
    if collection_island_blocked || runtime.node != *root || forced_back != 3 { return 45 }
    if CollectionLocaleLabel("[a]\nUno\n---\n[b]\nDos\n---\n", "b") != "Dos" { return 15 }
    if CollectionLocaleLabel("[a]\nUno\n---\n", "missing") != "" { return 16 }
    ProductionShopUI.Open(1)
    if !ProductionShopUI.IsOpen() || !ProductionShopUI.Back() || ProductionShopUI.IsOpen() ||
        production_navigation_backs != 0 { return 31 }
    production_route = "shop"
    ProductionShopUI.Request()
    if !ProductionShopUI.IsOpen() || production_route != "" { return 32 }
    ProductionShopUI.confirm = 100
    if !ProductionShopUI.Back() || !ProductionShopUI.IsOpen() || production_navigation_backs != 0 { return 33 }
    if !ProductionShopUI.Back() || ProductionShopUI.IsOpen() || production_navigation_backs != 1 { return 34 }
    production_route = "chest"
    ProductionShopUI.Request()
    if !ProductionShopUI.IsOpen() || production_route != "" { return 35 }
    if !ProductionShopUI.Back() || ProductionShopUI.IsOpen() || production_navigation_backs != 2 { return 36 }
    root.collection = true
    unused CopyCString("arcade.shovey-player", root.identity.id[:])
    unused CopyCString("arcade.shovey", entry.id[:])
    unused CopyCString("verified-catalog-digest", entry.sha256[:])
    leaf.identity.id = entry.id
    runtime.node = *leaf
    if CollectionShopQueue("buy") || CollectionShopQueue("shovey.gold") { return 1 }
    exists = false
    if CollectionShopQueue("shop") { return 2 }
    exists = true
    if !CollectionShopQueue("shop") || CollectionShopQueue("chest") { return 3 }
    CollectionShopNavigate()
    if writes != 0 || route_calls != 0 || collection_shop_request != "shop" { return 4 }
    verified = 1
    CollectionShopNavigate()
    if writes != 1 || written != "shop" || collection_shop_request != "" || collection_shop_locator.chain.count != 0 { return 5 }
    if !CollectionShopQueue("chest") { return 6 }
    CollectionShopNavigate()
    if writes != 2 || written != "chest" { return 7 }
    verified = -1
    if !CollectionShopQueue("shop") { return 8 }
    CollectionShopNavigate()
    if writes != 2 || collection_shop_request != "" { return 9 }
    verified = 1; routed = false
    if !CollectionShopQueue("chest") { return 10 }
    CollectionShopNavigate()
    if writes != 2 || collection_shop_request != "" { return 11 }
    routed = true; writable = false
    if !CollectionShopQueue("shop") { return 12 }
    CollectionShopNavigate()
    if backs != 1 || collection_shop_request != "" { return 13 }
    root.collection = false
    if CollectionShopQueue("shop") { return 14 }
    // Covers and game receive UTC day even though their frame clock is 17s.
    unused WebMain()
    if today_seen != 20000 || ShopUI.day != 20000 || covers != 1 { return 17 }
    ShopUI.open = true
    wall = 1728086399.0
    unused WebMain()
    if today_seen != 20000 || shop_frames != 1 { return 18 }
    wall = 1728086400.0
    unused WebMain()
    if today_seen != 20001 || shop_frames != 2 { return 19 }
    key = 256
    unused WebMain()
    if ShopUI.open || covers != 2 { return 20 }
    key = 0; ShopUI.open = true; is_mini = true
    before := ShopUI.pumps
    unused WebMain()
    if ShopUI.pumps != before || game_frames != 1 || shop_frames != 2 { return 21 }
    is_mini = false; web_covers_open = false; web_editor_open = true
    unused WebMain()
    if editor_frames != 1 { return 22 }
    if EntityShowPage("open") { return 23 }
    entity_ready = true
    if EntityShowPage("buy") || profile_calls != 0 { return 24 }
    if !EntityShowPage("leaderboard") || entity_heading != "shovey_shop_leaderboard" || !entity_visible { return 25 }
    entity_save = false
    if EntityShowPage("dew") || profile_calls != 1 { return 26 }
    if !EntityBack() || !entity_visible { return 27 }
    entity_save = true
    if !EntityShowPage("dew") || entity_heading != "shovey_shop_dew" { return 28 }
    entity_back = true
    if !EntityBack() || entity_heading != "shovey_shop_profile" || !entity_visible { return 29 }
    entity_back = false
    if !EntityBack() || entity_visible { return 30 }
    if EntityShowPage("referrals:bad/code") ||
        EntityShowPage("referrals:https://example.invalid/invite/abc_123") || referral_calls != 0 { return 46 }
    if !EntityShowPage("referrals") || referral_calls != 1 || referral_code[0] != 0 ||
        entity_heading != "shovey_shop_profile" || !entity_visible { return 47 }
    if !EntityShowPage("referrals:abc_123") || referral_calls != 2 ||
        TextUntilNul(referral_code[:]) != "abc_123" { return 48 }
    if !EntityShowPage("referrals:https://dew.waozi.xyz/invite/def-456?app=shovey") ||
        referral_calls != 3 || TextUntilNul(referral_code[:]) != "def-456" { return 49 }
    entity_save = false
    if EntityShowPage("referrals:other") || referral_calls != 3 { return 50 }
    return 42
}
'''
fixture = WORK / 'routes.zi'
fixture.write_text(source)
flags = [] if (ROOT / 'ziran.local.toml').exists() else ['--locked']
toolchain = Path(subprocess.check_output(['./scripts/ziran.sh', 'pkg', 'path', 'ziran', *flags], cwd=ROOT, text=True).strip())
entity = Path(subprocess.check_output(['./scripts/ziran.sh', 'pkg', 'path', 'entity', *flags], cwd=ROOT, text=True).strip())
kryon = Path(subprocess.check_output(['./scripts/ziran.sh', 'pkg', 'path', 'kryon', *flags], cwd=ROOT, text=True).strip())
tool = str(toolchain / 'build/bin/ziran')
subprocess.run([tool, 'bundle', '--root', str(WORK), '--module-path', str(ROOT / 'src'),
                '--module-path', str(toolchain / 'std'),
                '--module-path', f'std={toolchain / "std"}', '--entry', 'routes:Check',
                '--bind-host', 'routes',
                '--module-path', f'entity={entity / "src"}',
                '--module-path', f'kryon={kryon / "src/ui"}', '--module-path', f'kryon={kryon / "src/backend"}',
                '-o', str(WORK / 'routes.zx'), str(fixture)], cwd=ROOT, check=True)
result = subprocess.check_output([tool, 'run', str(WORK / 'routes.zx')], cwd=ROOT, text=True)
assert result.strip() == '42', result
host = (ROOT / 'src/player_host.zi').read_text()
assert 'name == "entity.game-shop"' in host
assert 'AppHostText(CollectionShopAnswer(request))' in host
assert 'AppHostText(CollectionDewAnswer(request))' in host
assert 'return CollectionShopAnswer(request[5:])' in host
assert 'AppHostText(ifx EntityShowPage(request) then "queued" else "unavailable")' in host
# The same node-owned title reads the game's existing state in every host;
# the game's confirmation UI still owns every purchase.
title = (ROOT / 'src/title_view.zi').read_text()
assert 'Shop.Pump(' in title and 'Wallet.ShopCoins()' in title
toolbar = function(ROOT / 'src/title_view.zi', 'Frame')
assert 'ShopBuy(' not in toolbar and 'ShopBuyCoins(' not in toolbar
web = (ROOT / 'src/web/game.zi').read_text()
assert web.index('ShoveyShopSetToday(today)') < web.index('if !AppMini() && web_covers_open')
assert 'today := cast(s64)AppNow() / 86400' in web
assert 'ShopUI.IsOpen()' in web and 'else { WebCovers() }' in web
for name in ('stall', 'chest-closed', 'trophy', 'coins', 'dew'):
    assert f'assets/shovey/shop/{name}.png' in title
profile_paths = function(ROOT / 'src/shop_state.zi', 'ShopProfilePath')
assert 'assets/shovey/shop/profile-96.png' in profile_paths
assert 'skin := Shop.Skin()' in toolbar
assert 'Shop.SkinPath()' in toolbar
assert '50204 + cast(u64)skin' in toolbar
assert 'assets/shovey/sprites/player-down.png' not in toolbar
assert 'ShopUI.SkinPath()' in web
# The collection builder embeds the exact binary files that the toolbar reads.
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('shop_player_builder', ROOT / 'scripts/player.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
assets = WORK / 'assets'
byte_count = builder.stage_shop_assets(assets)
staging = assets / 'shovey/shop'
assert byte_count == sum(path.stat().st_size for path in assets.rglob('*') if path.is_file())
for name in ('stall', 'chest-closed', 'chest-open', 'book', 'profile-96', 'trophy', 'coins', 'dew'):
    original = ROOT / 'assets/shovey/shop' / (name + '.png')
    assert original.read_bytes() == (staging / original.name).read_bytes(), original
expected_portraits = [ROOT / 'assets/shovey/shop' / 'profile-96.png'] + \
    [ROOT / 'assets/shovey/shop' / f'profile-skin-{skin}-96.png' for skin in range(1, 8)]
staged_portraits = sorted(path.name for path in staging.glob('profile*.png'))
expected_portrait_names = sorted(original.name for original in expected_portraits)
assert staged_portraits == expected_portrait_names, (staged_portraits, expected_portrait_names)
for original in expected_portraits:
    staged = staging / original.name
    assert staged.is_file(), original
    assert original.read_bytes() == staged.read_bytes(), original
    with Image.open(original) as picture:
        assert picture.mode == 'RGBA' and picture.size == (96, 96), original
        alpha = picture.getchannel('A').tobytes()
        pixels = np.asarray(picture)
        if original.name == 'profile-96.png':
            default_alpha = alpha
            default_pixels = pixels
            with Image.open(ROOT / 'assets/shovey/shop/profile.png') as full_size:
                resized = full_size.resize((96, 96), Image.Resampling.LANCZOS).convert('RGBA')
                assert np.array_equal(np.asarray(resized), pixels), original
        else:
            assert alpha == default_alpha, original
            assert np.array_equal(default_pixels[:, :, 3], pixels[:, :, 3]), original
            height, width, _ = pixels.shape
            ys, xs = np.ogrid[:height, :width]
            radius2 = (xs - 47.5) ** 2 + (ys - 47.5) ** 2
            base_rgb = default_pixels[:, :, :3].astype(int)
            band = (radius2 > 32.75 ** 2) & (radius2 <= 34.5 ** 2) & \
                (base_rgb[:, :, 1] > base_rgb[:, :, 0] + 20) & \
                (base_rgb[:, :, 1] > base_rgb[:, :, 2] + 20)
            ring = (radius2 > 32.75 ** 2) & ~band
            assert band.any()
            assert not np.any(np.all(pixels[:, :, :3][band] == default_pixels[:, :, :3][band], axis=1)), original
            assert np.array_equal(default_pixels[:, :, :3][ring], pixels[:, :, :3][ring]), original
            changed = np.any(default_pixels[:, :, :3] != pixels[:, :, :3], axis=2)
            assert changed.any() and not np.any(changed & ring), original
assert not (assets / 'shovey/sprites').exists()
for locale in (ROOT / 'src/locales').glob('*.txt'):
    assert locale.read_bytes() == (assets / 'shovey/locales' / locale.name).read_bytes(), locale
print('Shop host local tests: verified shop/chest routes, request-origin Back, pending/rejected navigation, write failure, service forwarding, mini gating, UTC source and exact staged icons passed')
