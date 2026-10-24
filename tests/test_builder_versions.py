"""Check builder compatibility decisions without generating clients."""
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BuilderVersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clients = Path(self.temporary.name) / 'clients'
        (self.clients / 'python').mkdir(parents=True)
        self.namespace = runpy.run_path(str(ROOT / 'messenger-builder'))
        self.check = self.namespace['check_target_version']
        self.check.__globals__['CLIENTS_DIR'] = self.clients
        self.check.__globals__['__version__'] = '1.10.6'

    def target(self, version):
        (self.clients / 'python' / 'target-version.txt').write_text(version, encoding='utf-8')

    def output(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.check('python')
        return output.getvalue()

    def test_matching_and_patch_versions_are_accepted(self):
        for version in ('1.10.6', '1.10.99', '1.10.7-rc.1'):
            self.target(version)
            self.assertEqual(self.output(), '')

    def test_minor_mismatch_warns(self):
        self.target('1.9.6')
        self.assertIn('Warning: minor version mismatch', self.output())

    def test_major_mismatch_blocks(self):
        self.target('2.10.6')
        with self.assertRaisesRegex(ValueError, 'Major version mismatch'):
            self.output()

    def test_missing_metadata_warns_and_invalid_metadata_blocks(self):
        self.assertIn('compatibility is unknown', self.output())
        self.target('invalid')
        with self.assertRaisesRegex(ValueError, 'Invalid target/server version'):
            self.output()

    def test_empty_checkout_displays_recovery_commands(self):
        main = self.namespace['main']
        main.__globals__['CLIENTS_DIR'] = self.clients
        main.__globals__['BANNER'] = ''
        previous_cwd, previous_argv = Path.cwd(), sys.argv
        try:
            os.chdir(self.temporary.name)
            subprocess.run(['git', 'init', '--quiet'], check=True)
            sys.argv = ['messenger-builder', 'python']
            with contextlib.redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as result:
                    main('')
            self.assertEqual(result.exception.code, 1)
            self.assertIn('--recurse-submodules', output.getvalue())
            self.assertIn('messenger-builder update-clients', output.getvalue())
        finally:
            os.chdir(previous_cwd)
            sys.argv = previous_argv


if __name__ == '__main__':
    unittest.main(verbosity=2)
