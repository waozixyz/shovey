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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_artifacts as artifacts


class DescriptorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'work/artifact-consumer')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def descriptor(self, files, **headers):
        rows = dict(schema='1', package='provider', artifact='support', platform='linux-x86_64-gnu', key='a' * 64)
        rows.update(headers)
        for name, content in files.items():
            file = self.root / name
            file.parent.mkdir(exist_ok=True, parents=True)
            file.write_text(content)
            rows[name] = hashlib.sha256(file.read_bytes()).hexdigest()
        descriptor = self.root / 'artifact.tsv'
        descriptor.write_text(''.join(f'{key}\t{value}\n' for key, value in rows.items()))
        return descriptor

    def test_integrity_and_expected_target(self):
        path = self.descriptor({'lib/support.a': 'archive'})
        artifact = artifacts.Artifact(path, artifact='support', platform='linux-x86_64-gnu')
        self.assertEqual(artifact.output('lib/support.a'), self.root / 'lib/support.a')
        with self.assertRaisesRegex(ValueError, 'platform'):
            artifacts.Artifact(path, platform='windows-x86_64-mingw')
        (self.root / 'lib/support.a').write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'digest'):
            artifacts.Artifact(path)

    def test_paths_and_undeclared_metadata(self):
        path = self.descriptor({'data': 'valid'})
        artifact = artifacts.Artifact(path)
        for name in ('../outside', '/etc/passwd', 'missing'):
            with self.assertRaises(ValueError):
                artifact.output(name)
        (self.root / 'escape').symlink_to(self.root.parent)
        with self.assertRaises(ValueError):
            artifact.path('escape/anything')
        with path.open('a') as file:
            file.write('schema\t1\n')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            artifacts.Artifact(path)

    def test_provider_archive_order_and_unknown_rows(self):
        path = self.descriptor({'second.a': 'second', 'first.a': 'first',
            'link.txt': 'archive\tsecond.a\nflag\t-Wl,--start-group\narchive\tfirst.a\nlibrary\t-lm\n'})
        artifact = artifacts.Artifact(path)
        self.assertEqual(artifact.link_flags(), [str(self.root / 'second.a'), '-Wl,--start-group',
                                                 str(self.root / 'first.a'), '-lm'])
        self.assertEqual(artifact.link_flags(ordinary_imports=True), ['-Wl,--start-group', '-lm'])
        path = self.descriptor({'link.txt': 'future-format\tignored\n'})
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            artifacts.Artifact(path).link_flags()

    def test_prerequisite_paths_are_relative_to_their_descriptor(self):
        child = self.root / 'support'
        child.mkdir()
        (child / 'dependency.a').write_text('dependency')
        (child / 'link.txt').write_text('archive\tdependency.a\n')
        rows = dict(schema='1', package='provider', artifact='crypto', platform='linux-x86_64-gnu', key='b' * 64)
        for name in ('dependency.a', 'link.txt'):
            rows[name] = artifacts.digest(child / name)
        descriptor = child / 'artifact.tsv'
        descriptor.write_text(''.join(f'{key}\t{value}\n' for key, value in rows.items()))
        parent = self.descriptor({'host.a': 'host', 'link.txt': 'archive\thost.a\n'})
        (self.root / 'dependencies.tsv').write_text(f'self:crypto\t{descriptor}\n')
        self.assertEqual(artifacts.Artifact(parent).link_flags(ordinary_imports=True),
                         [str(child / 'dependency.a')])
        (child / 'dependency.a').write_text('damaged')
        with self.assertRaisesRegex(ValueError, 'digest'):
            artifacts.Artifact(parent).link_flags(ordinary_imports=True)


def providers(ziran):
    """No overrides/source copies: exercise the published immutable graph."""
    ziran = str(Path(shutil.which(ziran) or ziran).absolute())
    work = ROOT / 'work/artifact-consumer/published'
    work.mkdir(parents=True, exist_ok=True)
    (work / 'ziran.toml').write_text('''[package]
name = "ShoveyArtifactConsumerTest"
[toolchain]
git = "https://github.com/ziranlang/ziran.git"
ref = "8442e7229595e4425ed8542911b144a64cddaf6c"
[dependencies.entity]
git = "https://github.com/waozixyz/entity.git"
ref = "fd77f4adc19769d3fa39c59ebfb65baa0ff80bd0"
[dependencies.kryon]
git = "https://github.com/kryonlabs/kryon.git"
ref = "80084e1b1cdf2fbb84704c9e2babc850e7783236"
''')
    env = artifacts.environment()
    env['TMPDIR'] = str(work)
    env['ZIRAN_PROJECT_ROOT'] = str(work)
    subprocess.run([ziran, 'lock'], cwd=work, check=True, env=env)
    profile = artifacts.request('entity:native-profile', 'linux-x86_64-gnu', ziran=ziran, project=work, env=env)
    # Ordinary Zi imports provide the native graph; foreign crypto archives come
    # from the prerequisite descriptor, with the provider's order preserved.
    flags = profile.link_flags(ordinary_imports=True)
    assert str(profile.output('libentity.a')) not in flags
    assert profile.output('entity.zx').stat().st_size > 1000
    renderer = artifacts.request('kryon:renderer-desktop', 'linux-x86_64-gnu', ziran=ziran, project=work, env=env)
    meta = renderer.renderer()
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
