"""Pages output preserves released bytes and rejects oversized deploy files."""
import contextlib
import copy
import io
import os
import subprocess
import textwrap
from unittest import mock
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_pages', ROOT / 'scripts/prepare-pages.py')
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


class PagesPackaging(unittest.TestCase):
    def fixture(self, folder, size):
        data = (b'full map and embedded Island\x00' * (size // 28 + 1))[:size]
        (folder / 'runtime.data').write_bytes(data)
        (folder / 'runtime.data.gz').write_bytes(b'obsolete oversized gzip')
        (folder / 'index.html').write_text((ROOT / 'site/index.html').read_text())
        for name in ('runtime.js', 'runtime.wasm', 'arcade.json'): (folder / name).write_bytes(name.encode())
        identity = hashlib.sha256()
        for name in ('runtime.js', 'runtime.wasm', 'runtime.data', 'arcade.json'):
            identity.update(name.encode() + b'\0'); identity.update((folder / name).read_bytes())
        (folder / 'build.json').write_text(json.dumps(dict(source_revision='released', version='0.6.164', assets_sha256=identity.hexdigest())))
        return data

    def test_exact_reassembly_boundaries_and_release_identity(self):
        work = ROOT / 'work/pages-packaging'; work.mkdir(parents=True, exist_ok=True)
        for size in (1, pages.CHUNK_SIZE, pages.CHUNK_SIZE + 1, 37323153):
            with self.subTest(size=size), tempfile.TemporaryDirectory(dir=work) as temporary:
                folder = Path(temporary)
                original = self.fixture(folder, size)
                original_identity = json.loads((folder / 'build.json').read_text())['assets_sha256']
                manifest = pages.prepare_pages(folder, 'packaging')
                chunks = [(folder / chunk['name']).read_bytes() for chunk in manifest['chunks']]
                self.assertEqual(b''.join(chunks), original)
                self.assertEqual(manifest['sha256'], hashlib.sha256(original).hexdigest())
                for chunk, content in zip(manifest['chunks'], chunks):
                    self.assertEqual(chunk['size'], len(content))
                    self.assertEqual(chunk['sha256'], hashlib.sha256(content).hexdigest())
                    self.assertLessEqual(len(content), pages.CHUNK_SIZE)
                    self.assertEqual(Path(chunk['name']).name, chunk['name'])
                self.assertFalse((folder / 'runtime.data').exists())
                self.assertFalse((folder / 'runtime.data.gz').exists())
                receipt = json.loads((folder / 'build.json').read_text())
                self.assertEqual(receipt['source_revision'], 'released')
                self.assertEqual(receipt['version'], '0.6.164')
                self.assertEqual(receipt['assets_sha256'], original_identity)
                self.assertEqual(receipt['packaging_revision'], 'packaging')
                self.assertTrue(all(p.stat().st_size <= pages.LIMIT for p in folder.rglob('*') if p.is_file()))

    def test_whole_output_limit_including_unrelated_file(self):
        work = ROOT / 'work/pages-packaging'; work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            folder = Path(temporary); self.fixture(folder, 10)
            with (folder / 'another.bin').open('wb') as stream: stream.truncate(pages.LIMIT + 1)
            with self.assertRaisesRegex(ValueError, 'another.bin'):
                pages.prepare_pages(folder, 'packaging')

    def test_preflight_symlinks_and_source_identity_before_mutation(self):
        work = ROOT / 'work/pages-packaging'; work.mkdir(parents=True, exist_ok=True)
        for name in ('runtime.data.part-0000', 'runtime.data.json', 'runtime.data', 'nested'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=work) as temporary:
                folder = Path(temporary); self.fixture(folder, 10)
                sentinel = folder / 'sentinel'; sentinel.write_bytes(b'owner data')
                path = folder / name; path.unlink(missing_ok=True); path.symlink_to(sentinel)
                with self.assertRaisesRegex(ValueError, 'Symlink'):
                    pages.prepare_pages(folder, 'packaging')
                self.assertEqual(sentinel.read_bytes(), b'owner data')
                self.assertFalse((folder / 'runtime.data.json').is_file() and name != 'runtime.data.json')
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            folder = Path(temporary); self.fixture(folder, 10)
            (folder/'runtime.wasm').write_bytes(b'wrong release')
            with self.assertRaisesRegex(ValueError, 'do not match'):
                pages.prepare_pages(folder, 'packaging')
            self.assertFalse((folder/'runtime.data.json').exists())

    def workflow_python(self, marker):
        source = (ROOT/'.github/workflows/web.yml').read_text()
        source = source[source.index(marker):]
        begin = source.index("          python3 - <<'PYCODE'")
        source = source[source.index('\n', begin)+1:]
        return textwrap.dedent(source[:source.index('          PYCODE')])

    def test_actual_workflow_artifact_binding(self):
        code = self.workflow_python('- name: Repackage the released site for Pages')
        good = [dict(sha='released'), dict(repository=dict(full_name='waozixyz/shovey'),
                    head_sha='released', path='.github/workflows/web.yml'),
                dict(jobs=[dict(name='Build the site from the newest release', conclusion='success')])]
        receipt = dict(version='0.6.164', source_revision='released')
        cases = [(good, receipt, True)]
        for at, key, value in ((1,'head_sha','wrong'), (1,'path','other.yml'),
                               (1,'repository',dict(full_name='other/repo')), (2,'jobs',[])):
            changed = copy.deepcopy(good); changed[at][key]=value
            cases.append((changed, receipt, False))
        cases.append((good, dict(version='0.6.163', source_revision='released'), False))
        cases.append((good, dict(version='0.6.164', source_revision='wrong'), False))
        for responses, build, accepted in cases:
            with mock.patch.dict(os.environ, SITE_RUN='41439077406', VERSION='0.6.164'), \
                 mock.patch('subprocess.check_output', side_effect=[json.dumps(v).encode() for v in responses]), \
                 mock.patch('builtins.open', return_value=io.StringIO(json.dumps(build))):
                if accepted: exec(code, {})
                else:
                    with self.assertRaises(AssertionError): exec(code, {})

    def test_actual_workflow_changed_path_gate(self):
        code = self.workflow_python('- id: scope')
        for paths, expected in (('scripts/prepare-pages.py\nsite/index.html', 'game=false'),
                                ('src/player.zi', 'game=true'), ('', 'game=true')):
            output = io.StringIO()
            with mock.patch.dict(os.environ, BEFORE='before'), \
                 mock.patch('subprocess.check_output', return_value=paths), contextlib.redirect_stdout(output):
                exec(code, {})
            self.assertEqual(output.getvalue().strip(), expected)


if __name__ == '__main__': unittest.main()
