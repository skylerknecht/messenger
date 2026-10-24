import contextlib
import copy
import io
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from messenger.manager import Manager, UpdateCLI
from messenger.scanner import Scanner
from messenger.supervisor import TaskSupervisor


PROFILES = ('handlers', 'messengers', 'forwarders', 'scanners')
TYPES = ('debug', 'success', 'warning', 'information', 'error')


class DisplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ui = UpdateCLI('messenger', None, None)
        self.manager = Manager.__new__(Manager)
        self.manager.update_cli = self.ui

    async def command(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            await self.manager.display_settings(*args)
        return output.getvalue()

    def visible(self, profile, status):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.ui.display('example', status, display_module=profile)
        return bool(output.getvalue())

    async def test_off_silences_all_four_profiles(self):
        table = await self.command('off')
        for profile in PROFILES:
            self.assertIn(profile, table)
            for status in TYPES:
                self.assertFalse(self.visible(profile, status), (profile, status))

    async def test_reset_restores_exact_startup_defaults(self):
        original = copy.deepcopy(self.ui.display_filters)
        await self.command('off')
        await self.command('debug')
        await self.command('reset')
        self.assertEqual(self.ui.display_filters, original)
        self.assertFalse(self.visible('handlers', 'warning'))
        self.assertTrue(self.visible('scanners', 'warning'))

    async def test_each_global_type_toggles_uniformly(self):
        for command, status in [('debug', 'debug'), ('success', 'success'), ('warning', 'warning'),
                                ('info', 'information'), ('error', 'error')]:
            with self.subTest(command=command):
                await self.command('off')
                await self.command(command)
                self.assertTrue(all(self.visible(profile, status) for profile in PROFILES))
                await self.command(command)
                self.assertFalse(any(self.visible(profile, status) for profile in PROFILES))

    async def test_mixed_states_become_consistent(self):
        await self.command('messengers', 'debug')
        await self.command('debug')
        self.assertTrue(all(self.visible(profile, 'debug') for profile in PROFILES))
        # Startup intentionally mixes handler warnings off with other warnings on.
        await self.command('warning')
        self.assertTrue(all(self.visible(profile, 'warning') for profile in PROFILES))

    async def test_profile_toggles_and_legacy_aliases(self):
        await self.command('scanners', 'infos,successes')
        self.assertFalse(self.visible('scanners', 'information'))
        self.assertFalse(self.visible('scanners', 'success'))
        self.assertTrue(self.visible('messengers', 'success'))
        await self.command('success,successes')
        self.assertTrue(all(self.visible(profile, 'success') for profile in PROFILES))

    async def test_invalid_types_do_not_partially_change_filters(self):
        original = copy.deepcopy(self.ui.display_filters)
        await self.command('scanners', 'warning,invalid')
        self.assertEqual(self.ui.display_filters, original)

    async def test_scanner_lifecycle_and_validation_follow_the_profile(self):
        messenger = types.SimpleNamespace(connected=False, supervisor=TaskSupervisor(self.ui))
        await self.command('off')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            Scanner('invalid/cidr', 'invalid-port', 1, self.ui, messenger, 1)
            scanner = Scanner('127.0.0.1', '80', 1, self.ui, messenger, 1)
            await scanner.start()
            await scanner.stop()
        self.assertEqual(output.getvalue(), '')
        await self.command('scanners', 'info,success,warning')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            scanner = Scanner('127.0.0.1', '80', 1, self.ui, messenger, 1)
            await scanner.start()
            await scanner.stop()
        self.assertIn('Starting scan', output.getvalue())
        self.assertIn('finished sending', output.getvalue())
        self.assertIn('has stopped', output.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
