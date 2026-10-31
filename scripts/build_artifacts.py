"""Shovey's consumer of Ziran artifact descriptors and provider link metadata.

Entity/Kryon Ziran modules remain ordinary imports in the player. Only foreign
support archives are linked: libentity's complete Ziran graph must not be
linked into that same graph a second time.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ('schema', 'package', 'artifact', 'platform', 'key')


def environment():
    env = dict(os.environ)
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
                'SESSION_MANAGER', 'GDK_DISPLAY', 'MFLAGS', 'MAKEOVERRIDES'):
        env.pop(key, None)
    env.update(MAKEFLAGS='-j1', CMAKE_BUILD_PARALLEL_LEVEL='1', EMCC_CORES='1',
               ZIRAN_PAR_THREADS='1', ZIRAN_BUILD_JOBS='1', YUE_DESKTOP_RECOVERY='0')
    return env


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Artifact:
    def __init__(self, descriptor, *, artifact=None, platform=None):
        self.descriptor = Path(descriptor)
        if not self.descriptor.is_absolute():
            raise ValueError('artifact descriptor must be absolute')
        self.root = self.descriptor.parent.resolve()
        self.rows = {}
        for line in self.descriptor.read_text().splitlines():
            name, value = line.split('\t', 1)
            if name in self.rows:
                raise ValueError('duplicate artifact row: ' + name)
            self.rows[name] = value
        if any(name not in self.rows for name in HEADERS) or self.rows['schema'] != '1':
            raise ValueError('unsupported artifact descriptor')
        if artifact and self.rows['artifact'] != artifact:
            raise ValueError('artifact selection mismatch')
        if platform and self.rows['platform'] != platform:
            raise ValueError('artifact platform mismatch')
        for name, value in self.rows.items():
            if name not in HEADERS:
                if not re.fullmatch('[0-9a-f]{64}', value) or digest(self.path(name)) != value:
                    raise ValueError('artifact digest mismatch: ' + name)

    def path(self, name):
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('artifact path escapes descriptor: ' + name)
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('artifact path escapes descriptor: ' + name)
        return path

    def output(self, name):
        if name in HEADERS or name not in self.rows:
            raise ValueError('undeclared artifact output: ' + name)
        return self.path(name)

    def renderer(self):
        meta = json.loads(self.output('renderer.json').read_text())
        if any(meta.get(key) != self.rows[key] for key in ('artifact', 'platform')) or meta.get('schema') != 1:
            raise ValueError('renderer metadata does not match descriptor')
        for field in ('archives', 'js_libraries'):
            meta[field] = [str(self.output(name)) for name in meta.get(field, [])]
        meta['include_directories'] = [str(self.path(name)) for name in meta['include_directories']]
        meta['resources'] = {key: str(self.output(name)) for key, name in meta['resources'].items()}
        meta['preload_files'] = [dict(path=str(self.output(item['path'])), mount=item['mount'])
                                 for item in meta.get('preload_files', [])]
        return meta

    def link_flags(self, *, ordinary_imports=False, seen=None):
        """Preserve provider row/edge order; skip its Zi archive for a Zi host."""
        seen = set() if seen is None else seen
        if self.descriptor in seen:
            raise ValueError('artifact dependency cycle')
        seen = seen | {self.descriptor}
        flags = []
        for line in self.output('link.txt').read_text().splitlines():
            kind, value = line.split('\t', 1)
            if kind == 'archive':
                path = self.output(value)
                if not ordinary_imports:
                    flags.append(str(path))
            elif kind == 'pkg-config':
                flags.extend(shlex.split(subprocess.check_output(
                    ['pkg-config', '--libs', *shlex.split(value)], text=True, env=environment())))
            elif kind in ('library', 'flag'):
                flags.append(value)
            elif kind == 'js-library':
                flags.extend(['--js-library', str(self.output(value))])
            elif kind == 'embed':
                name, mount = value.split('@', 1)
                flags.extend(['--embed-file', str(self.output(name)) + '@' + mount])
            else:
                raise ValueError('unsupported provider link row: ' + kind)
        dependencies = self.root / 'dependencies.tsv'
        if dependencies.exists():
            for line in dependencies.read_text().splitlines():
                _, descriptor = line.split('\t', 1)
                child = Artifact(descriptor, platform=self.rows['platform'])
                flags.extend(child.link_flags(seen=seen))
        return flags


def request(selection, platform, *, ziran=None, project=ROOT, env=None, options=()):
    project = Path(project)
    tool = ziran or str(ROOT / 'scripts/ziran.sh')
    if '/' in str(tool):
        tool = str(Path(tool).absolute())
    locked = [] if (project / 'ziran.local.toml').exists() else ['--locked']
    overrides = [part for value in options for part in ('--option', value)]
    descriptor = subprocess.check_output(
        [str(tool), 'pkg', 'artifact', selection, '--platform', platform, *overrides, *locked],
        cwd=project, text=True, env=env or environment()).strip()
    return Artifact(descriptor, artifact=selection.split(':', 1)[1], platform=platform)


def renderer_link(meta, *, preloads=True):
    flags = [*meta['archives'], *meta['link_flags']]
    for path in meta['js_libraries']:
        flags.extend(['--js-library', path])
    if preloads:
        for item in meta['preload_files']:
            flags.extend(['--preload-file', item['path'] + '@' + item['mount']])
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
    renderer = request('kryon:renderer-raylib', platform, ziran=args.ziran, env=env,
                       options=[f'kryon:renderer.android_ndk={args.ndk}',
                                f'kryon:renderer.android_api={args.api}']).renderer()
    values = dict(SHOVEY_CRYPTO_LINK=crypto.link_flags(),
                  SHOVEY_RENDERER_LINK=renderer_link(renderer),
                  SHOVEY_RENDERER_COMPILE=renderer['compile_flags'],
                  SHOVEY_RENDERER_INCLUDES=renderer['include_directories'],
                  SHOVEY_RENDERER_DEFINES=renderer['defines'])
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
        meta = request('kryon:renderer-web', 'emscripten-wasm32-emscripten',
                       ziran=args.ziran, env=env).renderer()
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
