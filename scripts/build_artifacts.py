"""Shovey's build choices over Ziran's artifact and Kryon's renderer consumers.

Entity/Kryon Ziran modules remain ordinary imports in the player. Only foreign
support archives are linked: libentity's complete Ziran graph must not be
linked into that same graph a second time.
"""
import argparse
import importlib.util
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
        meta = renderer(request('kryon:renderer-web', 'emscripten-wasm32-emscripten',
                                ziran=args.ziran, env=env))
        sources = sorted(args.generated.rglob('*.c'))
        includes = sorted({args.generated, *(path.parent for path in sources)})
        subprocess.run([args.cc, '-O2', '-I' + str(args.include),
                        *['-iquote' + str(path) for path in includes], *meta['compile_flags'],
                        *map(str, sources), *renderer_link(meta), '--preload-file',
                        str(args.assets) + '@/assets', '-o', str(args.output)], check=True, env=env)
    elif args.command == 'android-config':
        android_config(args)


if __name__ == '__main__':
    main()
