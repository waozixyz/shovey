#!/usr/bin/env python3
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def workflow_generator():
    workflow = (ROOT / '.github/workflows/play-bundle.yml').read_text()
    match = re.search(
        r"python3 - > build/play-notes/whatsnew-en-US <<'PY'\n(.*?)\n          PY\n",
        workflow,
        re.S,
    )
    if match is None:
        raise AssertionError('Play release-notes generator not found in workflow')
    return textwrap.dedent(match.group(1))


class PlayReleaseNotesTest(unittest.TestCase):
    def generated_file(self, notes):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as temporary:
            root = Path(temporary)
            (root / 'src').mkdir()
            (root / 'src/CHANGELOG.md').write_text(
                f'## [0.6.164] - 2026-11-02\n\n{notes}\n\n'
                '## [0.6.163] - 2026-11-01\n\nOlder release.\n'
            )
            output = root / 'whatsnew-en-US'
            environment = dict(os.environ, VERSION='0.6.164')
            with output.open('wb') as stream:
                subprocess.run(
                    [sys.executable, '-c', workflow_generator()],
                    cwd=root,
                    env=environment,
                    stdout=stream,
                    check=True,
                )
            return output.read_text()

    def test_generated_file_stays_within_play_limit_without_terminator(self):
        exact = 'a' * 500
        over = 'a' * 501
        multibyte = 'é' * 501
        self.assertEqual(self.generated_file(exact), exact)
        self.assertEqual(self.generated_file(over), 'a' * 499 + '…')
        self.assertEqual(self.generated_file(multibyte), 'é' * 499 + '…')
        self.assertEqual(len(self.generated_file(multibyte)), 500)


if __name__ == '__main__':
    unittest.main()
