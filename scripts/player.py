#!/usr/bin/env python3
"""Build Shovey's player, the standalone game people download, from this
package's own lock: its games, the shared Apps controller, the account
Profile and the native host for Linux, Windows, Android and the browser.

It is the host Arcade's standalone Shovey had: the collection keeps the
identity arcade.shovey-player, and the host the record folders and account
it used, so existing players keep their progress. Run `make levels
landscape` first; `make player-*` does.

    python3 scripts/player.py covers      remake assets/player after art changes
    python3 scripts/player.py collection  build/player/shovey.zx, shovey.json, entity.zx
    python3 scripts/player.py linux       build/player/linux and its download
    python3 scripts/player.py windows     build/player/windows and its download (MinGW)
    python3 scripts/player.py android [--release | --gplay | --bundle]
    python3 scripts/player.py site --release DIR [--output DIR]
"""
import argparse
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/player'
COVERS = ROOT / 'assets/player'
CONTROLLER_SHA256 = ROOT / 'packaging/apps-controller.sha256'
DOWNLOADS = ROOT / 'build/downloads'
# The collection's identity and the record folders it names stay those of
# Arcade's standalone Shovey.
COLLECTION_ID = 'arcade.shovey-player'
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024
# The desktop download: the player beside its collection, Profile and the
# small pictures it shows while the collection opens.
LINUX_DATA = ['shovey.zx', 'shovey.json', 'entity.zx', 'startup/shovey/title-portrait.png',
              'startup/shovey/title-landscape.png', 'startup/shovey/logo.png']
WINDOWS_DATA = ['shovey.zx', 'shovey.json', 'entity.zx', 'kryon-font.ttf']
WINDOWS_LIBRARIES = ['-lgdi32', '-lwinmm', '-lopengl32', '-luser32', '-lshell32', '-lole32', '-lcomdlg32',
                     '-lcomctl32', '-luuid', '-lws2_32', '-liphlpapi', '-lcrypt32', '-lsecur32', '-lbcrypt',
                     '-ladvapi32', '-lz', '-lm', '-lpthread']


def environment():
    env = {key: value for key, value in os.environ.items()
           if key not in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
    for key in ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES'):
        env.pop(key, None)
    return env


def run(command, **options):
    options.setdefault('env', environment())
    subprocess.run([str(part) for part in command], check=True, **options)


def lock():
    return [] if (ROOT / 'ziran.local.toml').exists() else ['--locked']


def package(name):
    """A locked package's checkout, a transitive one included."""
    if (ROOT / 'ziran.local.toml').exists() or shutil.which('ziran'):
        tool = 'ziran'
    else:
        # A clean checkout without Ziran (F-Droid) gets the locked toolchain.
        tool = str(ROOT / 'scripts/ziran.sh')
    return Path(subprocess.check_output([tool, 'pkg', 'path', name, *lock()], cwd=ROOT, text=True,
                                        env=environment()).strip())


def dependency(name, project):
    """A package's own locked dependency, by the name that package gives it."""
    return Path(subprocess.check_output([ziran(), 'pkg', 'path', name, '--locked'], cwd=project, text=True,
                                        env=environment()).strip())


def toolchain():
    """The built checkout of the toolchain this package locks: its own, the
    one CI's setup put on PATH, or one built here into build/toolchain."""
    source = package('ziran')
    if (source / 'build/bin/ziran').is_file() and (source / 'build/bin/zi2c').is_file():
        return source
    found = shutil.which('ziran')
    if found:
        root = Path(found).resolve().parents[2]
        head = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        if head and head == subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True,
                                           text=True).stdout.strip() and (root / 'build/bin/zi2c').is_file():
            return root
    private = ROOT / 'build/toolchain'
    stamp = private / 'source'
    if not (private / 'build/bin/ziran').is_file() or not stamp.is_file() or stamp.read_text() != str(source):
        if private.exists():
            shutil.rmtree(private)
        shutil.copytree(source, private, ignore=shutil.ignore_patterns('build'))
        run(['make', '-s', '-j2', '-C', private, 'all'])
        stamp.write_text(str(source))
    return private


def ziran():
    """The compiler this package locks."""
    return str(toolchain() / 'build/bin/ziran')


def release():
    """This release's version and Android version code, as update_version.sh wrote them."""
    version = json.loads((ROOT / 'version.json').read_text())
    current = re.search(r'^## \[([0-9.]+)\]', (ROOT / 'src/CHANGELOG.md').read_text(), re.M)
    if not current or current[1] != version['version']:
        raise SystemExit('Run update_version.sh: version.json differs from src/CHANGELOG.md')
    return version


def edition_version(manifest):
    """An edition's version: the newest release in the changelog beside its catalog."""
    changelog = (ROOT / manifest).with_name('CHANGELOG.md')
    current = re.search(r'^## \[([0-9.]+)\]', changelog.read_text(), re.M)
    if not current:
        raise SystemExit(f'{changelog} needs a numeric release entry')
    return current[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# The games.

def declared_apps():
    """The apps apps.json declares, with their catalogs, in dependency order."""
    declaration = json.loads((ROOT / 'apps.json').read_text())
    apps = []
    for app in declaration['apps']:
        manifest = ROOT / app['manifest']
        apps.append(dict(manifest=manifest, descriptor=json.loads(manifest.read_text()),
                         cover=app.get('cover'), requires=app.get('requires', []),
                         shared_code=app.get('shared_code', False),
                         shared_records=app.get('shared_records', []),
                         library_entries=app.get('library_entries', []), enabled=app.get('enabled', True)))
    by_id = {app['descriptor']['id']: app for app in apps}
    ordered, complete = [], set()

    def visit(app, visiting=()):
        identifier = app['descriptor']['id']
        if identifier in visiting:
            raise ValueError('Cyclic game dependency')
        if identifier in complete:
            return
        for dependency in app['requires']:
            if dependency not in by_id or (app['enabled'] and not by_id[dependency]['enabled']):
                raise ValueError(f'{identifier}: missing dependency {dependency}')
            visit(by_id[dependency], (*visiting, identifier))
        complete.add(identifier)
        ordered.append(app)

    for app in apps:
        visit(app)
    return declaration, [app for app in ordered if app['enabled']]


def shared_copies(app):
    path = app['manifest'].with_name('shared_assets.json')
    return json.loads(path.read_text())['copies'] if path.exists() else []


def share_resources(app, apps, resources, staged):
    """Alias only complete, byte-identical resources from a declared dependency,
    so an add-on such as the editor does not pack Classic's pictures twice."""
    by_id = {item['descriptor']['id']: item for item in apps}
    links = []
    for dependency in app['requires']:
        original = by_id[dependency]
        descriptor = original['descriptor']
        prefixes = [{'from': descriptor['assets'], 'to': ''}, *shared_copies(original)]
        original_root = staged / descriptor['name'] / 'assets' / descriptor['name']
        for copy in shared_copies(app):
            for prefix in prefixes:
                try:
                    relative = Path(copy['from']).relative_to(prefix['from'])
                except ValueError:
                    continue
                target = resources / copy['to']
                source = original_root / prefix['to'] / relative
                if not target.exists() or not source.exists() or target.is_dir() != source.is_dir():
                    continue
                if target.is_dir():
                    files = [p for p in target.rglob('*') if p.is_file()]
                    if not files or any(not (source / p.relative_to(target)).is_file() or
                                        p.read_bytes() != (source / p.relative_to(target)).read_bytes() for p in files):
                        continue
                    suffix = '/'
                else:
                    if target.read_bytes() != source.read_bytes():
                        continue
                    suffix = ''
                links.append(dict(dependency=dependency,
                    path=f'assets/{app["descriptor"]["name"]}/{Path(copy["to"]).as_posix()}' + suffix,
                    source=f'assets/{descriptor["name"]}/{(Path(prefix["to"]) / relative).as_posix()}' + suffix))
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                break
    if len(links) > 16:
        raise ValueError('Too many shared resource links')
    return dict(dependencies=app['requires'], resources=links)


def leave_out(rules_path, resources, release_build):
    """Removes what the game's bundle.json says its bundle leaves out."""
    rules = json.loads(rules_path.read_text()) if rules_path.exists() else {}
    patterns = rules.get('leave_out', []) + (rules.get('release_leave_out', []) if release_build else [])
    for pattern in patterns:
        for path in resources.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    art_path = resources / 'art.json'
    if patterns and art_path.exists():
        art = json.loads(art_path.read_text())
        art['files'] = [item for item in art['files'] if (resources / item['path']).is_file()]
        art_path.write_text(json.dumps(art, indent=2) + '\n')


def build_games(apps):
    """Each enabled game's portable bundle, built as Arcade builds it."""
    kryon, tools, entity = package('kryon'), toolchain(), package('entity')
    daochi_client = dependency('daochi_client', entity)
    crypto = dependency('crypto', daochi_client)
    staged_root, games = OUT / 'game-assets', OUT / 'games'
    games.mkdir(parents=True, exist_ok=True)
    by_id = {app['descriptor']['id']: app for app in apps}
    sys.path.insert(0, str(ROOT / 'scripts'))
    from release_assets import prepare_release_assets
    for app in apps:
        manifest, descriptor = app['manifest'], app['descriptor']
        if descriptor['kind'] != 'game' or descriptor['contract_version'] != 1 or descriptor['module_api'] != 2:
            raise ValueError(f'{manifest}: not a game for the player')
        name = descriptor['name']
        staged = staged_root / name
        shutil.rmtree(staged, ignore_errors=True)
        resources = staged / 'assets' / name
        resources.mkdir(parents=True)
        shutil.copytree(ROOT / descriptor['assets'], resources, dirs_exist_ok=True)
        for copy in shared_copies(app):
            source, target = ROOT / copy['from'], resources / copy['to']
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copyfile(source, target)
        (resources / 'catalog.json').write_text(json.dumps(
            {key: value for key, value in descriptor.items() if key not in ('build_defines', 'prepare_assets')},
            indent=2) + '\n')
        defines = descriptor.get('build_defines', [])
        if 'SHOVEY_RELEASE' in defines:
            prepare_release_assets(ROOT, resources)
        leave_out(manifest.with_name('bundle.json'), resources, 'SHOVEY_RELEASE' in defines)
        locales = resources / 'locales'
        locales.mkdir(exist_ok=True)
        translations = {}
        for locale in sorted((ROOT / descriptor['locales']).glob('*.txt')):
            blocks, values = [], {}
            for block in locale.read_text().split('---\n'):
                lines = block.splitlines()
                heading = next((line for line in lines if line), '')
                if heading.startswith('[' + descriptor['locale_prefix']):
                    body = '\n'.join(lines[lines.index(heading) + 1:]).rstrip()
                    blocks.append(heading + '\n' + body + '\n---\n')
                    values[heading[1:-1]] = body
            (locales / locale.name).write_text(''.join(blocks))
            translations[locale.stem] = values
        # Text also lives in the game itself, for hosts that only know their
        # own locale files.
        generated = OUT / 'game-generated' / name
        generated.mkdir(parents=True, exist_ok=True)
        shared = share_resources(app, apps, resources, staged_root)
        (games / (name + '-resources.json')).write_text(json.dumps(shared, indent=2) + '\n')
        if shared['dependencies']:
            # A base-art update must also invalidate cached editor images.
            required = shared | {'sha256': {identifier: digest(games / (by_id[identifier]['descriptor']['name'] + '.zx'))
                                            for identifier in shared['dependencies']}}
            (resources / 'requirements.json').write_text(json.dumps(required, sort_keys=True) + '\n')
        code = 'GameLocaleText :: (language: string, key: string) -> string {\n'
        for language, values in sorted(translations.items(), key=lambda item: item[0] == 'en'):
            if language != 'en':
                code += '    if language == ' + json.dumps(language) + ' {\n'
            for key, value in values.items():
                code += ('        ' if language != 'en' else '    ') + 'if key == ' + json.dumps(key) + \
                    ' { return ' + json.dumps(value, ensure_ascii=False) + ' }\n'
            if language != 'en':
                code += '    }\n'
        code += '    return ""\n}\n'
        (generated / 'translations.zi').write_text(code)
        bundle = games / (name + '.zx')
        source = ROOT / descriptor['source']
        run([ziran(), 'bundle', '--root', source.parent, '--module-path', ROOT / 'src',
             '--module-path', generated,
             '--module-path', kryon / 'src/ui', '--module-path', 'kryon=' + str(kryon / 'src/ui'),
             '--module-path', 'kryon=' + str(kryon / 'src/backend'),
             '--module-path', 'std=' + str(tools / 'std'), '--module-path', tools / 'std',
             '--module-path', 'apps=' + str(package('apps') / 'src'),
             '--module-path', 'mingcute=' + str(package('mingcute') / 'src'),
             '--module-path', 'entity=' + str(entity / 'src'),
             '--module-path', 'daochi_client=' + str(daochi_client),
             '--module-path', 'crypto=' + str(crypto / 'src'),
             *[flag for define in defines for flag in ('--define', define)],
             *[flag for entry in app['library_entries'] for flag in ('--retain', entry)],
             *[flag for dependency in app['requires'] if app['shared_code']
               for flag in ('--library', games / (by_id[dependency]['descriptor']['name'] + '.zx'))],
             '--define', 'KRYON_HOSTED_UI', '--asset-dir', 'assets=' + str(staged / 'assets'),
             '--entry', descriptor['entry'], '-o', bundle, source], cwd=ROOT)
        print(f'built {bundle.relative_to(ROOT)} ({bundle.stat().st_size // 1024} KiB)')


# The small cover and preview copies the collection packs.

PREVIEW_LONGEST, COVER_LONGEST, LOGO_LONGEST, COVER_QUALITY = 480, 640, 512, 85


def cover_art(apps):
    """(copy name, key, source bytes) for every enabled game's covers and preview."""
    for app in apps:
        name = app['descriptor']['name']
        yield name, 'preview', (ROOT / app['descriptor']['preview']).read_bytes()
        for key in ('portrait', 'landscape', 'logo'):
            if app['cover'] and key in app['cover']:
                yield name, key, (ROOT / app['cover'][key]).read_bytes()


def small_copy(data, key):
    """(bytes, suffix): opaque cover art as a JPEG, logos and previews as PNG."""
    from PIL import Image
    image = Image.open(io.BytesIO(data))
    image.load()
    longest = PREVIEW_LONGEST if key == 'preview' else LOGO_LONGEST if key == 'logo' else COVER_LONGEST
    scale = min(1.0, longest / max(image.size))
    alpha = 'A' in image.getbands() or 'transparency' in image.info
    photo = key in ('portrait', 'landscape') and not alpha
    if scale == 1.0 and key != 'preview' and not photo:
        return data, '.png'
    image = image.convert('RGBA' if alpha else 'RGB')
    if scale < 1.0:
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                             Image.Resampling.LANCZOS)
    if key == 'preview':
        if alpha:
            image = image.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
        else:
            image = image.quantize(256, dither=Image.Dither.FLOYDSTEINBERG)
    output = io.BytesIO()
    if photo:
        image.save(output, 'JPEG', quality=COVER_QUALITY, optimize=True, progressive=True)
        return output.getvalue(), '.jpg'
    image.save(output, 'PNG', optimize=True)
    return output.getvalue(), '.png'


def covers():
    """Remake the committed copies. The collection packs them as they are, so
    its bytes never depend on the local image library."""
    _, apps = declared_apps()
    COVERS.mkdir(parents=True, exist_ok=True)
    sources, written = {}, set()
    for name, key, data in cover_art(apps):
        contents, suffix = small_copy(data, key)
        (COVERS / f'{name}-{key}{suffix}').write_bytes(contents)
        written.add(f'{name}-{key}{suffix}')
        sources[f'{name}-{key}'] = {'source_sha256': hashlib.sha256(data).hexdigest()}
    for stale in [*COVERS.glob('*.png'), *COVERS.glob('*.jpg')]:
        if stale.name not in written:
            stale.unlink()
    (COVERS / 'sources.json').write_text(json.dumps(dict(sorted(sources.items())), indent=2) + '\n')
    print(f'{len(sources)} cover copies in {COVERS.relative_to(ROOT)}')


def cover_copy(name, key, source):
    """(bytes, suffix) of the committed copy, which must be of the current art."""
    sources = json.loads((COVERS / 'sources.json').read_text())
    if sources.get(f'{name}-{key}', {}).get('source_sha256') != hashlib.sha256(source).hexdigest():
        raise SystemExit(f'{name} {key} art changed; run python3 scripts/player.py covers')
    for suffix in ('.png', '.jpg'):
        if (COVERS / f'{name}-{key}{suffix}').is_file():
            return (COVERS / f'{name}-{key}{suffix}').read_bytes(), suffix
    raise SystemExit(f'{name} {key} has no copy; run python3 scripts/player.py covers')


# The collection.

def build_controller():
    """The shared Apps controller from the locked Apps package, accepted only
    with the digest this package trusts."""
    apps = package('apps')
    output = OUT / 'apps-ui'
    run([sys.executable, apps / 'scripts/build-ui.py', '--output', output], cwd=ROOT)
    controller = output / 'apps.zx'
    trusted = CONTROLLER_SHA256.read_text().strip()
    actual = digest(controller)
    if actual != trusted:
        raise SystemExit(f'The Apps controller differs from {CONTROLLER_SHA256.relative_to(ROOT)}: '
                         f'{actual} != {trusted}. Review the Apps update, then record its digest there.')
    return controller, actual


def build_entity():
    """The account Profile, which the player hosts beside the collection."""
    entity, kryon, tools, qrcode = (package(name) for name in ('entity', 'kryon', 'ziran', 'qrcode'))
    output = OUT / 'entity.zx'
    run([ziran(), 'bundle', '--root', entity, '--module-path', entity / 'src',
         '--module-path', kryon / 'src/ui', '--module-path', 'kryon=' + str(kryon / 'src/ui'),
         '--module-path', 'kryon=' + str(kryon / 'src/backend'), '--module-path', 'qrcode=' + str(qrcode / 'src'),
         '--module-path', tools / 'std', '--define', 'KRYON_HOSTED_UI',
         '--asset-dir', 'assets=' + str(entity / 'assets'), '--entry', 'entity:Main',
         '-o', output, entity / 'src/entity.zi'], cwd=entity)
    return output


def collection():
    version = release()
    declaration, apps = declared_apps()
    if declaration['id'] != COLLECTION_ID:
        raise SystemExit('apps.json must keep the collection identity ' + COLLECTION_ID)
    OUT.mkdir(parents=True, exist_ok=True)
    build_games(apps)
    controller, controller_digest = build_controller()
    staging = OUT / 'collection'
    if staging.exists():
        shutil.rmtree(staging)
    assets = staging / 'assets'
    (assets / 'apps').mkdir(parents=True)
    shutil.copyfile(controller, assets / 'apps/apps.zx')
    children, total = [], controller.stat().st_size
    for app in apps:
        descriptor = app['descriptor']
        name = descriptor['name']
        bundle = (OUT / 'games' / (name + '.zx')).read_bytes()
        preview, preview_suffix = cover_copy(name, 'preview', (ROOT / descriptor['preview']).read_bytes())
        copies = [(bundle, f'arcade/games/{name}.zx'), (preview, f'arcade/previews/{name}{preview_suffix}')]
        child = dict(id=descriptor['id'], title=descriptor['title'], bundle=f'assets/arcade/games/{name}.zx',
                     protocol='node/2', expected_id=name, version=edition_version(app['manifest']),
                     sha256=hashlib.sha256(bundle).hexdigest(), bytes=len(bundle),
                     preview=f'assets/arcade/previews/{name}{preview_suffix}',
                     icon=f'assets/arcade/previews/{name}{preview_suffix}')
        if app['shared_code']:
            child['shared_code'] = True
        if app['shared_records']:
            child['shared_records'] = app['shared_records']
        if app['requires']:
            shared = json.loads((OUT / 'games' / (name + '-resources.json')).read_text())
            child['dependencies'] = shared['dependencies']
            if shared['resources']:
                child['resources'] = shared['resources']
        if app['cover']:
            packed = {key: app['cover'][key] for key in ('caption', 'action') if key in app['cover']}
            for key in ('portrait', 'landscape', 'logo'):
                if key in app['cover']:
                    contents, suffix = cover_copy(name, key, (ROOT / app['cover'][key]).read_bytes())
                    packed[key] = f'assets/arcade/covers/{name}-{key}{suffix}'
                    copies.append((contents, f'arcade/covers/{name}-{key}{suffix}'))
            child['cover'] = packed
        for contents, relative in copies:
            target = assets / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
            total += len(contents)
        children.append(child)
    if total > MAX_PAYLOAD_BYTES:
        raise SystemExit("Shovey's collection exceeds the host's payload limit")
    catalog = dict(schema=1, id=COLLECTION_ID, title=declaration['title'], harness='assets/apps/apps.zx',
                   children=children)
    (assets / 'apps/catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
    payload = OUT / 'shovey.zx'
    run([ziran(), 'bundle', '--project', *lock(), '--root', ROOT / 'src', '--entry', 'player_collection:Main',
         '--asset-dir', 'assets=' + str(assets), '-o', payload, ROOT / 'src/player_collection.zi'], cwd=ROOT)
    if children[0]['version'] != version['version']:
        raise SystemExit('Classic is the collection; its changelog must name this release')
    receipt = dict(id=COLLECTION_ID, version=version['version'], sha256=digest(payload),
                   apps_sha256=controller_digest, children=children, source_mode='project')
    (OUT / 'shovey.json').write_text(json.dumps(receipt, indent=2) + '\n')
    build_entity()
    print(f'Shovey {version["version"]} collection: {payload.relative_to(ROOT)}')


def checked_collection():
    """The built collection, its receipt and Profile, after checking they match."""
    receipt = json.loads((OUT / 'shovey.json').read_text())
    if receipt['sha256'] != digest(OUT / 'shovey.zx') or receipt['version'] != release()['version']:
        raise SystemExit('The collection changed; run python3 scripts/player.py collection')
    if not (OUT / 'entity.zx').is_file():
        raise SystemExit('The Profile is missing; run python3 scripts/player.py collection')
    return receipt


# Native hosts.

def liboqs(folder, *configure):
    """Entity's post-quantum signatures, built once for each liboqs source."""
    source = package('liboqs')
    output = folder / 'lib/liboqs.a'
    stamp = folder / 'source'
    if output.exists() and stamp.exists() and stamp.read_text() == str(source):
        return output
    if folder.exists():
        shutil.rmtree(folder)
    run([*configure, 'cmake', '-S', source, '-B', folder, '-DCMAKE_BUILD_TYPE=MinSizeRel', '-DBUILD_SHARED_LIBS=OFF',
         '-DOQS_BUILD_ONLY_LIB=ON', '-DOQS_USE_OPENSSL=OFF', '-DOQS_DIST_BUILD=OFF', '-DOQS_OPT_TARGET=generic',
         '-DOQS_MINIMAL_BUILD=SIG_ml_dsa_44'])
    run(['cmake', '--build', folder, '--target', 'oqs', '-j2'])
    stamp.write_text(str(source))
    return output


def startup_art(output):
    """Small full-colour pictures the desktop player draws before the collection opens."""
    from PIL import Image
    startup = output / 'startup/shovey'
    startup.mkdir(parents=True, exist_ok=True)
    for name, edge in [('title-portrait.png', 640), ('title-landscape.png', 640), ('logo.png', 512)]:
        with Image.open(ROOT / 'assets/shovey' / name) as original:
            image = original.convert('RGBA' if 'A' in original.getbands() else 'RGB')
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            image.save(startup / name, optimize=True)


def linux():
    receipt = checked_collection()
    folder = OUT / 'linux'
    generated = folder / 'c'
    if generated.exists():
        shutil.rmtree(generated)
    run([ziran(), 'build', '--project', *lock(), '--target=c', '--define', 'PLATFORM_DESKTOP',
         '--entry', 'player_desktop:main', '-o', generated, 'src/player_desktop.zi'], cwd=ROOT)
    runtime = OUT / 'ziran-linux/libziran.a'
    stamp = runtime.parent / 'source'
    if not runtime.is_file() or not stamp.is_file() or stamp.read_text() != str(toolchain()):
        run(['make', '-B', '-j2', '-C', toolchain(), 'BUILD_DIR=' + str(runtime.parent), runtime])
        stamp.write_text(str(toolchain()))
    oqs = liboqs(OUT / 'oqs-linux')
    monocypher = package('monocypher')
    libraries = subprocess.check_output(['pkg-config', '--libs', 'sdl2', 'cairo', 'freetype2', 'fontconfig',
                                         'pangocairo', 'gtk+-3.0'], text=True).split()
    binary = folder / 'shovey'
    temporary = folder / 'shovey.new'
    run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-ffunction-sections', '-fdata-sections',
         '-I' + str(toolchain() / 'include'), '-iquote', generated,
         *[item for path in sorted(generated.rglob('*')) if path.is_dir() for item in ('-iquote', path)],
         *sorted(generated.rglob('*.c')), runtime,
         '-I' + str(monocypher / 'src'), monocypher / 'src/monocypher.c',
         # Entity's device keys sign with Monocypher's standard Ed25519.
         monocypher / 'src/optional/monocypher-ed25519.c', oqs,
         '-Wl,--gc-sections', *libraries, '-lX11', '-l:libcurl.so.4', '-lz', '-lm', '-lpthread', '-o', temporary])
    temporary.replace(binary)
    for name in ('shovey.zx', 'shovey.json', 'entity.zx'):
        shutil.copyfile(OUT / name, folder / name)
    startup_art(folder)
    from PIL import Image
    Image.open(ROOT / 'assets/branding/shovey-icon.png').resize((256, 256), Image.Resampling.LANCZOS).save(
        folder / 'shovey-icon.png')
    pack('linux', folder, receipt['version'])


def windows(tools):
    receipt = checked_collection()
    folder = OUT / 'windows'
    defines = ['--define', '_WIN32', '--define', 'PLATFORM_DESKTOP', '--define', '__x86_64__']
    ir, generated = folder / 'ir', folder / 'c'
    for path in (ir, generated):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
    run([ziran(), 'ir', '--project', *lock(), *defines, '-o', ir, 'src/player_windows.zi'], cwd=ROOT)
    run([ziran(), 'build', '--target=c', *defines, '--entry', 'player_windows:main', '--root', ir,
         '-o', generated, ir / 'player_windows.zir'], cwd=ROOT)

    def built(output, source):
        stamp = output.parent / (output.name + '.source')
        return output.exists() and stamp.exists() and stamp.read_text() == str(source)

    def record(output, source):
        (output.parent / (output.name + '.source')).write_text(str(source))

    def cmake(source, build, *options):
        if build.exists():
            shutil.rmtree(build)
        build.mkdir(parents=True)
        (build / 'mingw.cmake').write_text(f'''set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER {tools}gcc)
set(CMAKE_RC_COMPILER {tools}windres)
set(CMAKE_AR {tools}ar)
set(CMAKE_RANLIB {tools}ranlib)
set(CMAKE_FIND_ROOT_PATH /usr/x86_64-w64-mingw32)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
''')
        run(['cmake', '-S', source, '-B', build, '-DCMAKE_TOOLCHAIN_FILE=' + str(build / 'mingw.cmake'),
             '-DBUILD_SHARED_LIBS=OFF', *options])

    compiler = toolchain()
    runtime = folder / 'runtime/libziran.a'
    if not built(runtime, compiler):
        run(['make', '-B', '-j2', '-C', compiler, 'BOOTSTRAP=1', 'BUILD_DIR=' + str(runtime.parent),
             'CC=' + tools + 'gcc', 'AR=' + tools + 'ar', 'OBJCOPY=' + tools + 'objcopy', 'CFLAGS=-O2', runtime])
        record(runtime, compiler)
    # Windows raylib as Breeze ships it: RGFW and OpenGL 1.1.
    raylib_source = package('raylib') / 'src'
    raylib = folder / 'raylib/libraylib.a'
    if not built(raylib, raylib_source):
        copy = folder / 'raylib/source'
        if copy.exists():
            shutil.rmtree(copy)
        shutil.copytree(raylib_source, copy, ignore=shutil.ignore_patterns('*.o', '*.a'))
        run(['make', '-j2', '-C', copy, 'OS=Windows_NT', 'RAYLIB_SRC_PATH=.', 'RAYLIB_RELEASE_PATH=..',
             'PLATFORM=PLATFORM_DESKTOP_RGFW', 'GRAPHICS=GRAPHICS_API_OPENGL_11', 'RAYLIB_LIBTYPE=STATIC',
             'RAYLIB_MODULE_AUDIO=TRUE', 'RAYLIB_MODULE_MODELS=TRUE', 'CC=' + tools + 'gcc', 'AR=' + tools + 'ar',
             'RANLIB=' + tools + 'ranlib',
             'CUSTOM_CFLAGS=-DSUPPORT_FILEFORMAT_JPG=1 -DSUPPORT_FILEFORMAT_TTF=1 -O2 -ffunction-sections -fdata-sections'])
        record(raylib, raylib_source)
    # Entity's account network and signatures: curl over Windows TLS, liboqs.
    curl_source = package('curl')
    curl = folder / 'curl/install/lib/libcurl.a'
    if not built(curl, curl_source):
        cmake(curl_source, folder / 'curl', '-DCMAKE_BUILD_TYPE=Release',
              '-DCMAKE_INSTALL_PREFIX=' + str(folder / 'curl/install'), '-DBUILD_STATIC_LIBS=ON',
              '-DBUILD_CURL_EXE=OFF', '-DCURL_STATICLIB=ON', '-DCURL_USE_SCHANNEL=ON', '-DCURL_USE_OPENSSL=OFF',
              '-DCURL_USE_LIBPSL=OFF', '-DCURL_USE_LIBSSH2=OFF', '-DCURL_USE_GSSAPI=OFF', '-DUSE_NGHTTP2=OFF',
              '-DUSE_LIBIDN2=OFF', '-DCURL_ZSTD=OFF', '-DCURL_BROTLI=OFF', '-DCURL_DISABLE_LDAP=ON',
              '-DCURL_DISABLE_LDAPS=ON', '-DCURL_DISABLE_SMB=ON', '-DENABLE_CURL_MANUAL=OFF', '-DBUILD_EXAMPLES=OFF',
              '-DBUILD_LIBCURL_DOCS=OFF', '-DBUILD_MISC_DOCS=OFF', '-DBUILD_TESTING=OFF')
        run(['cmake', '--build', folder / 'curl', '--target', 'install', '-j2'])
        record(curl, curl_source)
    oqs_source = package('liboqs')
    oqs = folder / 'oqs/lib/liboqs.a'
    if not built(oqs, oqs_source):
        cmake(oqs_source, folder / 'oqs', '-DCMAKE_BUILD_TYPE=MinSizeRel', '-DOQS_BUILD_ONLY_LIB=ON',
              '-DOQS_USE_OPENSSL=OFF', '-DOQS_DIST_BUILD=OFF', '-DOQS_OPT_TARGET=generic',
              '-DOQS_MINIMAL_BUILD=SIG_ml_dsa_44')
        run(['cmake', '--build', folder / 'oqs', '--target', 'oqs', '-j2'])
        record(oqs, oqs_source)
    # The program's icon in Explorer and the taskbar.
    from PIL import Image
    Image.open(ROOT / 'assets/branding/shovey-icon.png').convert('RGBA').save(
        folder / 'shovey.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    (folder / 'shovey.rc').write_text('1 ICON "shovey.ico"\n')
    run([tools + 'windres', '-O', 'coff', '-o', 'shovey-resource.o', 'shovey.rc'], cwd=folder)
    monocypher = package('monocypher')
    program = folder / 'shovey.exe'
    temporary = folder / 'shovey.new.exe'
    includes = ['-I' + str(compiler / 'include'), '-I' + str(monocypher / 'src')]
    for path in sorted({generated, *(item for item in generated.rglob('*') if item.is_dir())}):
        includes += ['-iquote', str(path)]
    run([tools + 'gcc', '-std=c11', '-O2', '-ffunction-sections', '-fdata-sections', *includes,
         *sorted(generated.rglob('*.c')), monocypher / 'src/monocypher.c',
         monocypher / 'src/optional/monocypher-ed25519.c', runtime, oqs, curl, raylib, folder / 'shovey-resource.o',
         '-Wl,--gc-sections', '-static', '-static-libgcc', '-mwindows', *WINDOWS_LIBRARIES, '-o', temporary])
    run([tools + 'strip', temporary])
    temporary.replace(program)
    shutil.copyfile(package('kryon') / 'assets/fonts/LiberationSans-Regular.ttf', folder / 'kryon-font.ttf')
    for name in ('shovey.zx', 'shovey.json', 'entity.zx'):
        shutil.copyfile(OUT / name, folder / name)
    pack('windows', folder, receipt['version'])


def pack(platform, folder, version):
    """The download: the player and its files in one Shovey folder."""
    stamp = int(os.environ.get('SOURCE_DATE_EPOCH') or time.time())
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    if platform == 'linux':
        files = [('shovey', 0o755)] + [(name, 0o644) for name in LINUX_DATA]
        output = DOWNLOADS / f'shovey-v{version}-linux-x86_64.tar.gz'
        temporary = output.with_suffix('.new')
        with tarfile.open(temporary, 'w:gz') as archive:
            for name, mode in files:
                contents = (folder / name).read_bytes()
                entry = tarfile.TarInfo('shovey/' + name)
                entry.size, entry.mode, entry.mtime = len(contents), mode, stamp
                archive.addfile(entry, io.BytesIO(contents))
    else:
        files = [('shovey.exe', 0o755)] + [(name, 0o644) for name in WINDOWS_DATA]
        output = DOWNLOADS / f'shovey-v{version}-windows-x86_64.zip'
        temporary = output.with_suffix('.new')
        moment = time.gmtime(max(stamp, 315532800))[:6]
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, mode in files:
                entry = zipfile.ZipInfo('Shovey/' + name, moment)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = mode << 16
                archive.writestr(entry, (folder / name).read_bytes())
    temporary.replace(output)
    print(f'Shovey {version} {platform} download: {output}')


def android(mode, application_id=None, abis='arm64-v8a,armeabi-v7a', build_dir=None):
    """The APK (the normal and F-Droid edition, Google-free) or the Google
    Play edition's APK or App Bundle, on Kryon's Android host from this
    package's lock."""
    receipt = checked_collection()
    version = release()
    kryon, compiler, raylib = package('kryon'), toolchain(), package('raylib')
    assets = OUT / 'android/assets'
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True)
    for name in ('shovey.zx', 'shovey.json', 'entity.zx'):
        shutil.copyfile(OUT / name, assets / name)
    # Android before 10 has no font lookup; the Windows player ships the same font.
    shutil.copyfile(kryon / 'assets/fonts/LiberationSans-Regular.ttf', assets / 'kryon-font.ttf')
    # Kryon's scaffold makes the Gradle project and its activity from the
    # locked Kryon; Shovey's module, CMake and manifest replace its own.
    droid = ROOT / 'droid'
    activity = droid / 'app/src/main/java/xyz/waozi/shovey/ShoveyActivity.java'
    for generated in (activity, droid / 'app/build.gradle', droid / 'app/src/main/AndroidManifest.xml',
                      droid / 'app/src/main/cpp/CMakeLists.txt'):
        generated.unlink(missing_ok=True)
    run([sys.executable, kryon / 'scripts/android_scaffold.py', '--root', ROOT, '--name', 'Shovey',
         '--package', 'xyz.waozi.shovey', '--activity', 'ShoveyActivity', '--kryon', kryon], cwd=ROOT)
    packaging = ROOT / 'packaging/android'
    shutil.copyfile(packaging / 'build.gradle', droid / 'app/build.gradle')
    shutil.copyfile(packaging / 'AndroidManifest.xml', droid / 'app/src/main/AndroidManifest.xml')
    shutil.copyfile(packaging / 'CMakeLists.txt', droid / 'app/src/main/cpp/CMakeLists.txt')
    (droid / 'gradle.properties').write_text(
        'org.gradle.daemon=false\norg.gradle.parallel=false\norg.gradle.workers.max=1\n'
        'org.gradle.jvmargs=-Xmx1024m -Dfile.encoding=UTF-8\n')
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or Path.home() / 'Android/Sdk')
    env = environment()
    env.update(ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk), LIBOQS_DIR=str(package('liboqs')),
               MONOCYPHER_DIR=str(package('monocypher')), CMAKE_BUILD_PARALLEL_LEVEL='1')
    task = {'debug': 'assembleDebug', 'release': 'assembleRelease', 'gplay': 'assembleRelease',
            'bundle': 'bundleRelease'}[mode]
    command = ['sh', droid / 'gradlew', '-p', droid, '--no-daemon', '--max-workers=1', '-Papp.abis=' + abis,
               '-Pkryon.dir=' + str(kryon), '-Pziran.dir=' + str(compiler), '-Praylib.dir=' + str(raylib / 'src'),
               '-Pandroid.aapt2FromMavenOverride=' + str(sdk / 'build-tools/36.0.0/aapt2')]
    # Kryon's Google Play edition adds Play Billing, so Dew is bought through
    # Play; only it may carry a Google library.
    if mode in ('gplay', 'bundle'):
        command += ['-Papp.edition=gplay', '-Pandroid.useAndroidX=true']
    if application_id:
        command.append('-Papp.id=' + application_id)
    if build_dir:
        command.append('-Papp.outputDir=' + str(Path(build_dir).resolve()))
    run([*command, task], cwd=ROOT, env=env)
    app_output = Path(build_dir).resolve() if build_dir else droid / 'app/build'
    folder = OUT / 'android'
    test = '-test' if application_id else ''
    if mode == 'bundle':
        output = folder / f'shovey{test}-unsigned.aab'
        shutil.copyfile(app_output / 'outputs/bundle/release/app-release.aab', output)
    elif mode in ('release', 'gplay'):
        edition = '-gplay' if mode == 'gplay' else ''
        output = folder / f'shovey{test}{edition}-unsigned.apk'
        shutil.copyfile(app_output / 'outputs/apk/release/app-release-unsigned.apk', output)
    else:
        output = folder / f'shovey{test}.apk'
        shutil.copyfile(app_output / 'outputs/apk/debug/app-debug.apk', output)
    print(f'Shovey {version["version"]} ({version["version_code"]}) for Android, '
          f'collection {receipt["sha256"][:12]}: {output}')


# The website.

def compress(path):
    """A gzip copy beside path, which the page fetches first: Cloudflare Pages
    does not compress binary files."""
    with open(path.with_name(path.name + '.gz'), 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', compresslevel=9, fileobj=raw, mtime=0) as packed:
            packed.write(path.read_bytes())


def site(release_folder, output):
    """shovey.waozi.xyz: a released download's own shovey.zx, shovey.json and
    entity.zx, unchanged, in the player compiled for the browser. Their
    programs are compiled into the page; the page still opens those bytes."""
    release_folder = release_folder.resolve()
    bundle = release_folder / 'shovey.zx'
    receipt = json.loads((release_folder / 'shovey.json').read_text())
    if receipt.get('id') != COLLECTION_ID or digest(bundle) != receipt.get('sha256'):
        raise SystemExit('The release does not match its shovey.json')
    profile = release_folder / 'entity.zx'
    # The player reads the receipt into a 4 KiB buffer.
    text = json.dumps(receipt, separators=(',', ':'))
    if len(text.encode()) >= 4096:
        raise SystemExit('The receipt exceeds the player buffer')
    work = OUT / 'web'
    work.mkdir(parents=True, exist_ok=True)
    env = environment()
    env['ZIRAN'] = str(toolchain() / 'build/bin/ziran')
    run([sys.executable, package('entity') / 'scripts/build-web.py', '--bundle', bundle, '--profile', profile,
         '--output', work / 'runtime.html', '--linked', bundle, '--linked', profile,
         '--entry', 'player_web:main', '--source', 'src/player_web.zi'], cwd=ROOT, env=env)
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(ROOT / 'site', output)
    shutil.copyfile(ROOT / 'src/web/privacy.html', output / 'privacy.html')
    shutil.copyfile(ROOT / 'assets/branding/shovey-social.png', output / 'og.png')
    page_pictures(output)
    for name in ('runtime.js', 'runtime.wasm', 'runtime.data'):
        shutil.copyfile(work / name, output / name)
    compress(output / 'runtime.data')
    (output / 'arcade.json').write_text(text)
    # One cache key for the runtime, its data and the collection it opens.
    page = output / 'index.html'
    html = page.read_text()
    revision = hashlib.sha256()
    for name in ('runtime.js', 'runtime.wasm', 'runtime.data', 'arcade.json'):
        revision.update(name.encode() + b'\0')
        revision.update((output / name).read_bytes())
    page.write_text(html.replace('__ARCADE_ASSET_REVISION__', revision.hexdigest()))
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    (output / 'build.json').write_text(json.dumps({'source_revision': source, 'version': receipt['version'],
                                                   'assets_sha256': revision.hexdigest()}) + '\n')
    print(f'shovey.waozi.xyz runs the released Shovey {receipt["version"]} in {output}')


# The loading screen's small pictures: (published name, source, longest edge).
PAGE_PICTURES = [
    ('icon.png', 'assets/branding/shovey-icon.png', 512),
    ('icon-192.png', 'assets/branding/shovey-icon.png', 192),
    ('logo.png', 'assets/shovey/logo.png', 720),
    ('title-landscape.jpg', 'assets/shovey/title-landscape.png', 1280),
    ('title-portrait.jpg', 'assets/shovey/title-portrait.png', 1280),
]


def page_pictures(output):
    from PIL import Image
    output.mkdir(parents=True, exist_ok=True)
    for name, source, longest in PAGE_PICTURES:
        target = output / name
        with Image.open(ROOT / source) as image:
            image.load()
            alpha = 'A' in image.getbands()
            image = image.convert('RGBA' if alpha else 'RGB')
            scale = min(1.0, longest / max(image.size))
            if scale < 1.0:
                image = image.resize((round(image.width * scale), round(image.height * scale)),
                                     Image.Resampling.LANCZOS)
            if target.suffix == '.jpg':
                image.save(target, 'JPEG', quality=82, optimize=True, progressive=True)
            else:
                image.save(target, 'PNG', optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('covers')
    commands.add_parser('collection')
    commands.add_parser('linux')
    win = commands.add_parser('windows')
    win.add_argument('--tools', default='x86_64-w64-mingw32-', help='the MinGW tool prefix')
    droid = commands.add_parser('android')
    kind = droid.add_mutually_exclusive_group()
    kind.add_argument('--release', action='store_true', help='the unsigned release APK for the signer')
    kind.add_argument('--gplay', action='store_true', help="the Google Play edition's unsigned release APK")
    kind.add_argument('--bundle', action='store_true', help="the Google Play edition's unsigned App Bundle")
    droid.add_argument('--application-id', help='an isolated package for device tests')
    droid.add_argument('--abis', default='arm64-v8a,armeabi-v7a')
    droid.add_argument('--build-dir', help='separate Gradle and CMake output for verification')
    web = commands.add_parser('site')
    web.add_argument('--release', type=Path, required=True,
                     help="an unpacked release folder: its shovey.zx, shovey.json and entity.zx")
    web.add_argument('--output', type=Path, default=ROOT / 'build/web-site')
    pictures = commands.add_parser('pictures', help="only the loading screen's small pictures (make web)")
    pictures.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'covers':
        covers()
    elif args.command == 'collection':
        collection()
    elif args.command == 'linux':
        linux()
    elif args.command == 'windows':
        windows(args.tools)
    elif args.command == 'android':
        android('bundle' if args.bundle else 'gplay' if args.gplay else 'release' if args.release else 'debug',
                args.application_id, args.abis, args.build_dir)
    elif args.command == 'site':
        site(args.release, args.output)
    else:
        page_pictures(args.output)


if __name__ == '__main__':
    main()
