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

    def test_actual_retry_input_validation_and_step_conditions(self):
        workflow = (ROOT / '.github/workflows/play-bundle.yml').read_text()
        self.assertRegex(workflow, r'      bundle_only:\n        description: [^\n]+\n        type: boolean\n        default: false')
        steps = re.split(r'(?=^      - )', workflow, flags=re.M)
        def step(name):
            return next(block for block in steps if block.startswith('      - name: '+name+'\n'))
        validation = textwrap.dedent(step('Validate the fixed revision').split('        run: |\n', 1)[1])
        def enabled(name, products_only, bundle_only):
            match = re.search(r'^        if: (.+)$', step(name), re.M)
            if not match: return True
            return {'${{ !inputs.products_only }}': not products_only,
                    '${{ !inputs.bundle_only }}': not bundle_only}[match[1]]
        for products_only, bundle_only, upload, products in (
                (False, False, True, True), (True, False, False, True),
                (False, True, True, False), (True, True, False, False)):
            with self.subTest(products_only=products_only, bundle_only=bundle_only):
                env = dict(os.environ, REVISION='1e91a0df921522b155dc4d0443cf424e6ee76ea0',
                           PRODUCTS_ONLY=str(products_only).lower(), BUNDLE_ONLY=str(bundle_only).lower())
                result = subprocess.run(['bash','--noprofile','--norc','-eo','pipefail','-c',validation],
                                        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 1 if products_only and bundle_only else 0)
                if result.returncode: continue  # No build or external action may run.
                for name in ('Build the Google Play edition bundle','Sign and verify the bundle',
                             'Write the release notes','Upload to Google Play internal testing'):
                    self.assertEqual(enabled(name,products_only,bundle_only), upload)
                self.assertEqual(enabled('Sell the Dew packs at Google Play prices',products_only,bundle_only), products)


if __name__ == '__main__':
    unittest.main()
