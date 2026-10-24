"""Check server keep-alive framing and compatibility with generated clients."""
import contextlib
import argparse
import asyncio
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from messenger.engine import Engine
from messenger.manager import Manager
from messenger.message import CheckInMessage, CheckOutMessage, SendDataMessage
from messenger.messengers import HTTPMessenger, WebSocketMessenger
from messenger.text import strip_ansi
from test_polling import render_client


KEY = hashlib.sha256(b'keep-alive-test').digest()


class Output:
    def __init__(self):
        self.messages = []

    def display(self, text, *args, **kwargs):
        self.messages.append(text)


class AdaptivePollingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.output = Output()
        self.engine = Engine([], self.output, KEY)
        self.http = HTTPMessenger('127.0.0.1', 'test', self.output, self.engine._serialize)
        self.http.nickname = 'dc01'

    async def test_adaptive_on_by_default_and_off_uses_real_encrypted_framing(self):
        self.assertTrue(self.http.adaptative)
        self.assertEqual(await self.engine.get_downstream_messages(self.http), b'')
        self.http.adaptative = False
        frame = await self.engine.get_downstream_messages(self.http)
        messages = self.engine._deserialize(frame)
        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], SendDataMessage)
        self.assertEqual(messages[0].client_id, '')
        self.assertEqual(len(messages[0].data), 16)
        self.assertEqual(self.http.sent_bytes, len(frame))
        self.assertTrue(self.http.downstream_messages.empty())

    async def test_appends_after_real_messages_and_respects_batch_limit(self):
        self.http.adaptative = False
        real = SendDataMessage('real-client', b'payload')
        await self.http.send_message_downstream(real)
        messages = self.engine._deserialize(await self.engine.get_downstream_messages(self.http))
        self.assertEqual(messages[0], real)
        self.assertEqual(messages[1].client_id, '')
        for _ in range(self.http.MAX_BATCH_SIZE):
            await self.http.send_message_downstream(real)
        messages = self.engine._deserialize(await self.engine.get_downstream_messages(self.http))
        self.assertEqual(messages, [real] * self.http.MAX_BATCH_SIZE)

    async def test_checkout_and_websocket_do_not_get_keep_alive_frames(self):
        self.http.adaptative = False
        self.http.checked_out = True
        await self.http.send_message_downstream(CheckOutMessage())
        self.assertEqual(self.engine._deserialize(await self.engine.get_downstream_messages(self.http)),
                         [CheckOutMessage()])
        self.assertEqual(await self.engine.get_downstream_messages(self.http), b'')
        ws = WebSocketMessenger(types.SimpleNamespace(closed=False), '127.0.0.1', 'test',
                                self.output, self.engine._serialize)
        self.assertFalse(hasattr(ws, 'adaptative'))
        self.assertEqual(await self.engine.get_downstream_messages(ws), b'')

    async def test_command_toggles_by_name_and_current_selection(self):
        manager = Manager.__new__(Manager)
        manager.messengers = [self.http]
        manager.current_messenger = None
        manager.update_cli = self.output
        manager.commands = {'adaptative': (manager.adaptative, '')}
        await manager.execute_command('adaptative', ['dc01'])
        self.assertFalse(self.http.adaptative)
        manager.current_messenger = self.http
        with contextlib.redirect_stdout(io.StringIO()) as detail:
            manager._print_messenger_detail(self.http)
        self.assertIn('Adaptive:    off', detail.getvalue())
        await manager.execute_command('adaptative', [])
        self.assertTrue(self.http.adaptative)
        self.http.checked_out = True
        await manager.adaptative()
        self.assertTrue(self.http.adaptative)
        self.assertIn('killed', self.output.messages[-1])
        manager.current_messenger = WebSocketMessenger(types.SimpleNamespace(closed=False), '127.0.0.1',
                                                       'test', self.output, self.engine._serialize)
        await manager.adaptative()
        self.assertIn('only available for HTTP', self.output.messages[-1])

    async def test_reconnect_preserves_the_setting(self):
        self.http.adaptative = False
        self.engine.messengers.append(self.http)
        checkin = self.engine._serialize([CheckInMessage(self.http.identifier)])
        target = await self.engine.checkin_http(checkin, '127.0.0.1', 'test')
        self.assertIs(target, self.http)
        self.assertFalse(target.adaptative)

    async def test_killed_status_for_both_transports(self):
        ws = WebSocketMessenger(types.SimpleNamespace(closed=False), '127.0.0.1', 'test',
                                self.output, self.engine._serialize)
        for messenger in (self.http, ws):
            messenger.checked_out = True
            self.assertEqual(strip_ansi(messenger.status), 'killed')

    async def test_python_client_ignores_dummy_data(self):
        self.http.adaptative = False
        frame = await self.engine.get_downstream_messages(self.http)
        namespace = {}
        prefix = render_client('python').split('async def main():', 1)[0]
        exec(compile(prefix, '<rendered Python client>', 'exec'), namespace)
        client = namespace['HTTPClient']('http://localhost', KEY, 'test', '')
        for message in client.deserialize_messages(frame):
            await client.dispatch_message(message)
        self.assertEqual(client.tcp_clients, {})
        self.assertTrue(client.upstream_messages.empty())
        self.assertFalse(client.killed)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required')
    async def test_node_client_ignores_dummy_data(self):
        self.http.adaptative = False
        frame = await self.engine.get_downstream_messages(self.http)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'client.js'
            source.write_text(render_client('nodejs'), encoding='utf-8')
            await asyncio.to_thread(subprocess.run,
                                    ['node', str(ROOT / 'tests/keep_alive_node.js'), str(source), frame.hex(), KEY.hex()],
                                    check=True, timeout=10)

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('MESSENGER_CSC'),
                         'Set MESSENGER_CSC to a .NET Framework-compatible Roslyn csc.exe')
    async def test_csharp_client_ignores_dummy_data(self):
        self.http.adaptative = False
        frame = await self.engine.get_downstream_messages(self.http)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = importlib.util.spec_from_file_location('keep_alive_csharp_builder',
                                                         ROOT / 'builder/clients/csharp/builder.py')
            builder = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(builder)
            parser = argparse.ArgumentParser()
            builder.add_arguments(parser)
            args = parser.parse_args(['--name', str(root), '--no-print', '-e', 'test'])
            with contextlib.redirect_stdout(io.StringIO()):
                builder.build(args)
            compiler = os.environ['MESSENGER_CSC']
            library = root / 'client.dll'
            await asyncio.to_thread(subprocess.run,
                                    [compiler, '/nologo', '/warn:0', '/target:library', '/reference:System.Net.Http.dll',
                                     '/out:' + str(library)] + [str(p) for p in root.glob('*.cs')],
                                    check=True, timeout=30)
            executable = root / 'keep_alive.exe'
            await asyncio.to_thread(subprocess.run,
                                    [compiler, '/nologo', '/reference:' + str(library), '/out:' + str(executable),
                                     str(ROOT / 'tests/keep_alive_csharp.cs')], check=True, timeout=30)
            await asyncio.to_thread(subprocess.run, [str(executable), frame.hex(), KEY.hex()], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
