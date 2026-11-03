"""Shovey's build choices over Ziran's artifact and Kryon's renderer consumers.

Entity/Kryon Ziran modules remain ordinary imports in the player. Only foreign
support archives are linked: libentity's complete Ziran graph must not be
linked into that same graph a second time.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
shared_scripts = {}


def environment():
    env = dict(os.environ)
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
                'SESSION_MANAGER', 'GDK_DISPLAY', 'MFLAGS', 'MAKEOVERRIDES'):
        env.pop(key, None)
    env.update(MAKEFLAGS='-j1', CMAKE_BUILD_PARALLEL_LEVEL='1', EMCC_CORES='1',
               ZIRAN_PAR_THREADS='1', ZIRAN_BUILD_JOBS='1', YUE_DESKTOP_RECOVERY='0')
    return env


def shared_script(owner, name):
    """A build helper from the package that owns it, through the locked graph."""
    if name not in shared_scripts:
        lock = [] if (ROOT / 'ziran.local.toml').exists() else ['--locked']
        package = Path(subprocess.check_output([str(ROOT / 'scripts/ziran.sh'), 'pkg', 'path', owner, *lock],
                                               cwd=ROOT, text=True, env=environment()).strip())
        spec = importlib.util.spec_from_file_location(name, package / 'scripts' / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        shared_scripts[name] = module
    return shared_scripts[name]


def request(selection, platform, *, ziran=None, project=ROOT, env=None, options=()):
    return shared_script('ziran', 'ziran_artifacts').request(
        selection, platform, project=project, ziran=ziran or ROOT / 'scripts/ziran.sh',
        env=env or environment(), options=options)


def renderer(artifact):
    return shared_script('kryon', 'renderer_artifact').renderer_metadata(artifact)


def renderer_link(meta, *, preloads=True):
    return shared_script('kryon', 'renderer_artifact').renderer_link(meta, preloads=preloads)


def preload_groups(files, limit=24 * 1024 * 1024):
    """Keep original resource bytes in packages below Pages' 25 MiB limit."""
    groups, group, size = [], [], 0
    for path, mount in files:
        length = path.stat().st_size
        if length > limit:
            raise ValueError(f'Web resource exceeds the package limit: {path}')
        if group and size + length > limit:
            groups.append(group)
            group, size = [], 0
        group.append((path, mount))
        size += length
    if group:
        groups.append(group)
    return groups


def web_preloads(args, meta, profile, env):
    files = [(Path(item['path']), item['mount']) for item in meta.get('preload_files', [])]
    files += [(path, '/assets/' + path.relative_to(args.assets).as_posix())
              for path in sorted(args.assets.rglob('*')) if path.is_file()]
    files.append((profile.output('entity.zx'), '/entity.zx'))
    packager = Path(shutil.which(args.cc) or args.cc).resolve().parent / 'tools/file_packager'
    staging = args.generated.parent / 'preloads'
    staging.mkdir(parents=True, exist_ok=True)
    flags = []
    for index, group in enumerate(preload_groups(files)):
        data = args.output.with_name(f'{args.output.stem}-assets-{index}.data')
        script = staging / f'assets-{index}.js'
        subprocess.run([str(packager), str(data), '--preload',
                        *[str(path.resolve()) + '@' + mount for path, mount in group],
                        '--js-output=' + str(script), '--no-node'], check=True, env=env)
        flags += ['--pre-js', str(script)]
    args.output.with_name('preload-manifest.json').write_text(json.dumps([
        dict(path=mount, bytes=path.stat().st_size,
             sha256=hashlib.file_digest(path.open('rb'), 'sha256').hexdigest())
        for path, mount in files], indent=2) + '\n')
    return flags


def android_config(args):
    """Generate CMake inputs from descriptors; packaging keeps NativeActivity."""
    arch, prefix = {'arm64-v8a': ('aarch64', 'aarch64-linux-android'),
                    'armeabi-v7a': ('armv7', 'armv7a-linux-androideabi')}[args.abi]
    tools = args.ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    env = environment()
    env.update(CC=str(tools / f'{prefix}{args.api}-clang'), AR=str(tools / 'llvm-ar'))
    platform = f'android-{arch}-bionic'
    crypto = request('entity:native-crypto', platform, ziran=args.ziran, env=env,
                     options=[f'entity:edition={args.edition}', f'entity:ndk={args.ndk}',
                              f'entity:android_api={args.api}'])
    meta = renderer(request('kryon:renderer-raylib', platform, ziran=args.ziran, env=env,
                            options=[f'kryon:renderer.android_ndk={args.ndk}',
                                     f'kryon:renderer.android_api={args.api}']))
    values = dict(SHOVEY_CRYPTO_LINK=crypto.link_flags(env=env),
                  SHOVEY_RENDERER_LINK=renderer_link(meta),
                  SHOVEY_RENDERER_COMPILE=meta['compile_flags'],
                  SHOVEY_RENDERER_INCLUDES=meta['include_directories'],
                  SHOVEY_RENDERER_DEFINES=meta['defines'])
    def quote(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace(';', '\\;') + '"'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(''.join(f'set({name}\n' + ''.join('  ' + quote(value) + '\n' for value in flags) + ')\n'
                                   for name, flags in values.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ziran')
    sub = parser.add_subparsers(dest='command', required=True)
    link = sub.add_parser('web-link')
    link.add_argument('--cc', required=True)
    link.add_argument('--generated', type=Path, required=True)
    link.add_argument('--include', type=Path, required=True)
    link.add_argument('--assets', type=Path, required=True)
    link.add_argument('--output', type=Path, required=True)
    copy = sub.add_parser('profile')
    copy.add_argument('--output', type=Path, required=True)
    android = sub.add_parser('android-config')
    android.add_argument('--ndk', type=Path, required=True)
    android.add_argument('--abi', choices=('arm64-v8a', 'armeabi-v7a'), required=True)
    android.add_argument('--api', type=int, required=True)
    android.add_argument('--edition', choices=('direct', 'fdroid', 'play'), required=True)
    android.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'profile':
        profile = request('entity:native-profile', 'linux-x86_64-gnu', ziran=args.ziran)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(profile.output('entity.zx'), args.output)
    elif args.command == 'web-link':
        env = environment()
        env['CC'] = str(Path(shutil.which(args.cc) or args.cc).absolute())
        env['AR'] = str(Path(env['CC']).with_name('emar'))
        meta = renderer(request('kryon:renderer-web', 'emscripten-wasm32-emscripten',
                                ziran=args.ziran, env=env))
        crypto = request('entity:native-crypto', 'emscripten-wasm32-emscripten',
                         ziran=args.ziran, env=env)
        # The normal ZX profile is platform independent; share the artifact
        # already consumed by the native player and the ZX browser edition.
        profile = request('entity:native-profile', 'linux-x86_64-gnu',
                          ziran=args.ziran, env=environment())
        sources = sorted(args.generated.rglob('*.c'))
        includes = sorted({args.generated, *(path.parent for path in sources)})
        preloads = web_preloads(args, meta, profile, env)
        subprocess.run([args.cc, '-O2', '-I' + str(args.include),
                        *['-iquote' + str(path) for path in includes], *meta['compile_flags'],
                        *map(str, sources), *renderer_link(meta, preloads=False), *crypto.link_flags(env=env),
                        *preloads,
                        '-o', str(args.output)], check=True, env=env)
    elif args.command == 'android-config':
        android_config(args)


if __name__ == '__main__':
    main()
