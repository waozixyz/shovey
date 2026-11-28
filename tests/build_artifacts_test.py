"""Descriptor boundary tests and real published provider consumption."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_artifacts as artifacts
import player


class HostReuseTest(unittest.TestCase):
    def test_current_headers_flags_sources_and_libraries_are_used(self):
        compiler = shutil.which('cc')
        cache = shutil.which('ccache')
        if not compiler or not cache:
            self.skipTest('native compiler and ccache are needed for the reuse check')
        with tempfile.TemporaryDirectory(dir=ROOT / 'work/artifact-consumer') as temporary:
            folder = Path(temporary)
            header, source = folder / 'value.h', folder / 'main.c'
            header.write_text('#define VALUE 7\n')
            source.write_text('#include "value.h"\n#include <stdio.h>\n'
                              '#ifndef OFFSET\n#define OFFSET 0\n#endif\n'
                              'int reward(void);\nint main(void) { printf("%d\\n", VALUE + OFFSET + reward()); }\n')
            library_source = folder / 'reward.c'
            library = folder / 'reward.o'
            def reward(value):
                library_source.write_text(f'int reward(void) {{ return {value}; }}\n')
                subprocess.run([compiler, '-c', str(library_source), '-o', str(library)], check=True)
            reward(1)
            env = artifacts.environment() | {'XDG_CACHE_HOME': str(folder / 'cache')}
            binary = folder / 'host'
            def build(expected, flags=()):
                player.link_host(compiler, ['-std=c11', '-O2', *flags], [source], [library], binary, env=env)
                self.assertEqual(subprocess.check_output([binary], text=True).strip(), str(expected))
            build(8)
            build(8)
            stats = subprocess.check_output([cache, '--print-stats'], text=True,
                env=env | {'CCACHE_DIR': str(folder / 'cache/shovey-ccache')})
            counts = dict(line.split() for line in stats.splitlines())
            self.assertGreaterEqual(int(counts['direct_cache_hit']), 1)
            header.write_text('#define VALUE 11\n')
            build(12)
            build(17, ['-DOFFSET=5'])
            source.write_text(source.read_text().replace('VALUE + OFFSET', 'VALUE * 2 + OFFSET'))
            build(28, ['-DOFFSET=5'])
            reward(3)
            build(30, ['-DOFFSET=5'])
            # Downstream hosts without ccache still build and link current inputs.
            with patch.object(player.shutil, 'which', return_value=None):
                build(25)


class DescriptorTest(unittest.TestCase):
    """Descriptor rules belong to Ziran's own tests; this covers Shovey's use of them."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'work/artifact-consumer')
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def descriptor(self, files):
        rows = dict(schema='1', package='provider', artifact='support', platform='linux-x86_64-gnu', key='a' * 64)
        for name, content in files.items():
            (self.root / name).write_text(content)
            rows[name] = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        descriptor = self.root / 'artifact.tsv'
        descriptor.write_text(''.join(f'{key}\t{value}\n' for key, value in rows.items()))
        return descriptor

    def test_player_skips_only_the_archive_it_compiles_itself(self):
        path = self.descriptor({'host.a': 'host', 'link.txt': 'archive\thost.a\nlibrary\t-lm\n'})
        consumer = artifacts.shared_script('ziran', 'ziran_artifacts')
        self.assertEqual(consumer.Artifact(path).link_flags(), [str(self.root / 'host.a'), '-lm'])
        self.assertEqual(consumer.Artifact(path).link_flags(include_archives=False), ['-lm'])

    def test_requests_use_the_project_wrapper_and_clean_environment(self):
        path = self.descriptor({'data': 'valid'})
        real = subprocess.check_output
        calls = []
        def output(command, **options):
            if 'artifact' not in command:
                return real(command, **options)
            calls.append((command, options))
            return str(path)
        with patch.dict(os.environ, DISPLAY=':99'), patch.object(subprocess, 'check_output', side_effect=output):
            result = artifacts.request('provider:support', 'linux-x86_64-gnu')
        self.assertEqual(result.output('data'), self.root / 'data')
        command, options = calls[0]
        self.assertEqual(command[0], str(ROOT / 'scripts/ziran.sh'))
        self.assertNotIn('DISPLAY', options['env'])

    def test_web_link_keeps_native_profile_compiler(self):
        calls = []
        class Artifact:
            def output(self, name):
                return self.root / name

            def link_flags(self, **options):
                return []

        artifact = Artifact()
        artifact.root = self.root
        (self.root / 'entity.zx').write_bytes(b'profile')
        def request(selection, platform, **options):
            calls.append((selection, platform, options['env']))
            return artifact

        metadata = dict(compile_flags=[])
        arguments = ['build_artifacts.py', 'web-link', '--cc', '/toolchain/emcc',
                     '--include', str(self.root), '--generated', str(self.root),
                     '--assets', str(self.root), '--output', str(self.root / 'index.js')]
        with patch.dict(os.environ, CC='/usr/bin/cc', AR='/usr/bin/ar'), \
             patch.object(sys, 'argv', arguments), \
             patch.object(artifacts, 'request', side_effect=request), \
             patch.object(artifacts, 'renderer', return_value=metadata), \
             patch.object(artifacts, 'renderer_link', return_value=[]), \
             patch.object(subprocess, 'run') as link:
            artifacts.main()
        self.assertEqual([(name, platform) for name, platform, _ in calls], [
            ('kryon:renderer-web', 'emscripten-wasm32-emscripten'),
            ('entity:native-crypto', 'emscripten-wasm32-emscripten'),
            ('entity:native-profile', 'linux-x86_64-gnu')])
        self.assertEqual(calls[0][2]['CC'], '/toolchain/emcc')
        self.assertEqual(calls[1][2]['AR'], '/toolchain/emar')
        self.assertEqual(calls[2][2]['CC'], '/usr/bin/cc')
        self.assertEqual(calls[2][2]['AR'], '/usr/bin/ar')
        command = link.call_args.args[0]
        self.assertNotIn('--embed-file', command)
        self.assertNotIn('--preload-file', command)
        self.assertIn('--pre-js', command)
        packages = [call.args[0] for call in link.call_args_list[:-1]]
        self.assertTrue(any(str(self.root / 'entity.zx') + '@/entity.zx' in argv for argv in packages))

    def test_preload_groups_keep_every_resource_and_mount_within_limit(self):
        files = []
        for name, size in [('art.webp', 3), ('font.ttf', 3), ('entity.zx', 4)]:
            path = self.root / name
            path.write_bytes(b'x' * size)
            files.append((path, '/' + name))
        groups = artifacts.preload_groups(files, limit=6)
        self.assertEqual(groups, [files[:2], files[2:]])
        self.assertEqual([item for group in groups for item in group], files)
        self.assertTrue(all(sum(path.stat().st_size for path, _ in group) <= 6 for group in groups))
        with self.assertRaisesRegex(ValueError, 'exceeds the package limit'):
            artifacts.preload_groups(files, limit=2)

    def test_android_wrapper_preserves_startup_arguments_and_cleans_stale_instrumentation(self):
        with patch.object(player, 'OUT', self.root), patch.dict(os.environ, KRYON_TEST_DRIVER='1'):
            player.android_test_resources('xyz.waozi.shovey.test', 'armeabi-v7a,arm64-v8a')
            resources = self.root / 'android/test-driver-resources'
            for abi in ('armeabi-v7a', 'arm64-v8a'):
                script = resources / 'lib' / abi / 'wrap.sh'
                subprocess.run(['sh', '-n', script], check=True)
                # Exercise argv forwarding without touching a phone data directory.
                text = script.read_text().replace('/data/user/0/xyz.waozi.shovey.test/files/kryon-test-driver', str(self.root / 'driver'))
                result = subprocess.check_output(['sh', '-c', text, 'wrap', sys.executable, '-c',
                    'import os,sys; print(os.environ["KRYON_TEST_DRIVER"]); print(repr(sys.argv[1:]))', 'two words', '$literal'], text=True)
                self.assertEqual(result.splitlines(), [str(self.root / 'driver'), "['two words', '$literal']"])
            with patch.dict(os.environ, KRYON_TEST_DRIVER=''):
                player.android_test_resources('xyz.waozi.shovey', 'armeabi-v7a')
            self.assertFalse(resources.exists(), 'normal builds must remove stale debug startup files')


def providers(ziran):
    """No overrides/source copies: exercise the published immutable graph."""
    ziran = str(Path(shutil.which(ziran) or ziran).absolute())
    work = ROOT / 'work/artifact-consumer/published'
    work.mkdir(parents=True, exist_ok=True)
    (work / 'ziran.toml').write_text('''[package]
name = "ShoveyArtifactConsumerTest"
[toolchain]
git = "https://github.com/ziranlang/ziran.git"
ref = "3e69203b3e9217223d71754d7118e764e6b23ba5"
[dependencies.entity]
git = "https://github.com/waozixyz/entity.git"
ref = "78a79e8bf19d72f6afd1a941bc410b75d08854a3"
[dependencies.kryon]
git = "https://github.com/kryonlabs/kryon.git"
ref = "a5e4a8322b5bab1ba3483a82601028604b86e965"
''')
    env = artifacts.environment()
    env['TMPDIR'] = str(work)
    env['ZIRAN_PROJECT_ROOT'] = str(work)
    subprocess.run([ziran, 'lock'], cwd=work, check=True, env=env)
    profile = artifacts.request('entity:native-profile', 'linux-x86_64-gnu', ziran=ziran, project=work, env=env)
    # Ordinary Zi imports provide the native graph; foreign crypto archives come
    # from the prerequisite descriptor, with the provider's order preserved.
    flags = profile.link_flags(include_archives=False)
    assert str(profile.output('libentity.a')) not in flags
    assert profile.output('entity.zx').stat().st_size > 1000
    renderer = artifacts.request('kryon:renderer-desktop', 'linux-x86_64-gnu', ziran=ziran, project=work, env=env)
    meta = artifacts.renderer(renderer)
    assert Path(meta['resources']['font']).stat().st_size > 100000
    again = artifacts.request('entity:native-profile', 'linux-x86_64-gnu', ziran=ziran, project=work, env=env)
    assert again.descriptor == profile.descriptor, 'clean package artifacts must reuse descriptors'
    # Compile a small foreign support consumer using only the ordered metadata.
    source = work / 'consumer.c'
    source.write_text('extern void crypto_wipe(void *, unsigned long);\n'
                      'int main(void) { unsigned char bytes[4]={1,2,3,4}; '
                      'crypto_wipe(bytes, sizeof bytes); return bytes[0] != 0; }\n')
    binary = work / 'consumer'
    subprocess.run(['cc', str(source), *flags, '-o', str(binary)], check=True, env=env)
    subprocess.run([binary], check=True, env=env)
    (work / 'receipt.json').write_text(json.dumps(dict(profile=str(profile.descriptor),
        renderer=str(renderer.descriptor), graph=json.loads((work / 'ziran.lock').read_text())), indent=2) + '\n')
    print('PASS published Entity/Kryon descriptors, hashes, ordered crypto link/run and clean cache reuse', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--providers', action='store_true')
    parser.add_argument('--ziran', default=shutil.which('ziran') or str(ROOT / 'scripts/ziran.sh'))
    args = parser.parse_args()
    subprocess.run(['git', 'check-ignore', 'work/artifact-consumer/probe'], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    (ROOT / 'work/artifact-consumer').mkdir(parents=True, exist_ok=True)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case)
                               for case in (DescriptorTest, HostReuseTest))
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)
    if args.providers:
        providers(args.ziran)
