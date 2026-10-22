"""Publication retries keep the checked artifact and do not replay an upload."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publish', ROOT / 'scripts/publish-approved.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class Publication(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / 'build')
        self.root = Path(self.directory.name)
        self.store = self.root / 'build/approved-releases/inbe.arcade'
        self.store.mkdir(parents=True)
        (self.root / 'backup').mkdir()
        (self.root / 'build').mkdir(exist_ok=True)
        payload = b'ZIB\0checked release'
        self.digest = hashlib.sha256(payload).hexdigest()
        self.payload = self.store / (self.digest + '.zib')
        self.payload.write_bytes(payload)
        (self.root / 'build/arcade.zib').write_bytes(payload)
        self.release = dict(version='0.6.7', artifacts=[dict(sha256=self.digest, size=len(payload))])
        (self.store / 'latest-v2.json').write_text(json.dumps(self.release))
        self.receipt = dict(versions=dict(arcade='0.6.7'), sha256=self.digest,
                            approved_levels=19, phase='uploading')
        self.publisher = Mock()
        self.publisher.served_release.return_value = self.release
        self.config = dict(arcade=str(self.root), install_local=True)

    def tearDown(self):
        self.directory.cleanup()

    def complete(self, run=None):
        with patch.object(publish, 'ROOT', self.root), \
                patch.object(publish, 'release_publisher', return_value=self.publisher), \
                patch.object(publish, 'status'), \
                patch.object(publish.subprocess, 'run', run or Mock()):
            publish.complete_release(self.config, self.receipt, io.StringIO())

    def test_uploaded_release_is_verified_and_installed_without_rebuilding(self):
        run = Mock()
        self.complete(run)
        self.publisher.publish_node_app.assert_not_called()
        self.publisher.verify_node_app.assert_called_once()
        self.assertEqual(run.call_args.args[0], ['make', '-o', 'all', 'install'])
        self.assertEqual(self.receipt['phase'], 'verified')
        self.assertTrue(self.receipt['local_installed'])

    def test_retry_after_verification_error_uses_same_artifact(self):
        run = Mock()
        self.publisher.verify_node_app.side_effect = ValueError('public connection failed')
        with self.assertRaises(ValueError):
            self.complete(run)
        run.assert_not_called()
        self.assertEqual(self.receipt['phase'], 'uploading')
        self.publisher.verify_node_app.side_effect = None
        self.complete(run)
        self.publisher.publish_node_app.assert_not_called()
        self.assertEqual(self.receipt['sha256'], self.digest)

    def test_local_install_failure_keeps_published_receipt_for_retry(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.complete(Mock(side_effect=subprocess.CalledProcessError(1, 'make')))
        self.assertEqual(self.receipt['phase'], 'published')
        self.complete()
        self.assertEqual(self.receipt['phase'], 'verified')
        self.publisher.publish_node_app.assert_not_called()

    def test_changed_staged_artifact_is_refused(self):
        self.payload.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.complete()
        self.publisher.served_release.assert_not_called()
        self.publisher.publish_node_app.assert_not_called()


if __name__ == '__main__':
    unittest.main()
