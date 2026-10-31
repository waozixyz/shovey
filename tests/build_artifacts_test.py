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
    if not unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DescriptorTest)).wasSuccessful():
        raise SystemExit(1)
    if args.providers:
        providers(args.ziran)
