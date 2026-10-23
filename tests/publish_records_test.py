"""The approval worker commits only the published campaign and release records."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publisher_module', ROOT / 'scripts/publish-approved.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def git(repository, *arguments):
    return subprocess.check_output(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', *arguments],
                                   cwd=repository, text=True).strip()


class ReleaseRecords(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.origin, self.checkout = base / 'origin.git', base / 'checkout'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'master', str(self.origin)], check=True)
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(self.checkout)], check=True, stderr=subprocess.DEVNULL)
        git(self.checkout, 'checkout', '-q', '-b', 'master')
        git(self.checkout, 'config', 'user.name', 'Test')
        git(self.checkout, 'config', 'user.email', 'test@example.invalid')
        for name in ('CHANGELOG.md', 'VERSION', 'other.txt'):
            (self.checkout / name).write_text('old\n')
        git(self.checkout, 'add', '.')
        git(self.checkout, 'commit', '-q', '-m', 'Start')
        git(self.checkout, 'push', '-q', 'origin', 'master')
        module.STATE = base

    def tearDown(self):
        self.temporary.cleanup()

    def commit(self):
        with open(os.devnull, 'w') as output:
            return module.commit_paths(self.checkout, ['CHANGELOG.md', 'VERSION'], 'Record 1.0.1', output)

    def test_only_the_named_records_are_committed_and_pushed(self):
        (self.checkout / 'CHANGELOG.md').write_text('new\n')
        (self.checkout / 'other.txt').write_text('unrelated work\n')
        commit = self.commit()
        self.assertEqual(git(self.origin, 'rev-parse', 'master'), commit)
        self.assertEqual(git(self.checkout, 'show', '--name-only', '--format=%s', commit).split(), ['Record', '1.0.1', 'CHANGELOG.md'])
        self.assertEqual(git(self.checkout, 'status', '--porcelain'), 'M other.txt')

    def test_unchanged_records_keep_the_current_commit(self):
        head = git(self.checkout, 'rev-parse', 'HEAD')
        self.assertEqual(self.commit(), head)
        self.assertEqual(git(self.origin, 'rev-parse', 'master'), head)


if __name__ == '__main__':
    unittest.main()
