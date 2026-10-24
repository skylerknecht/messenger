"""Exercise the HTTP polling templates without opening network connections."""
import ast
import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]


def render_client(language, fixed=False, electron=False):
    env = Environment(loader=FileSystemLoader(str(ROOT / 'builder/clients' / language / 'templates')),
                      trim_blocks=True, lstrip_blocks=True)
    filename = {'python': 'client.py', 'nodejs': 'client.js', 'csharp': 'HttpServiceClient.cs'}[language]
    return env.get_template(filename).render(
        no_print=True, no_arg_parsing=True, no_adaptive_polling=fixed, exit_on_close=False,
        non_main_thread=False, electron=electron, server_url='http://localhost:8080',
        encryption_key='test-key', user_agent='test', proxy='', retry_duration=1, retry_attempts=1)


class CheckInMessage:
    def __init__(self, messenger_id=None):
        self.messenger_id = messenger_id


class CheckOutMessage:
    pass


class ClientBase:
    def __init__(self, key):
        self.killed = False
        self.identifier = 'test'

    async def readvertise_forwarders(self):
        pass

    async def dispatch_message(self, message):
        pass

    def handle_checkout(self):
        self.killed = True


def python_client(fixed=False):
    import random
    import ssl
    import urllib.request
    tree = ast.parse(render_client('python', fixed))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'HTTPClient')
    namespace = dict(Client=ClientBase, asyncio=asyncio, ssl=ssl, request=urllib.request, random=random,
                     CheckInMessage=CheckInMessage, CheckOutMessage=CheckOutMessage, MAX_BATCH_SIZE=100)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), '<rendered HTTPClient>', 'exec'), namespace)
    return namespace['HTTPClient']('http://localhost:8080', b'test', 'test', '')


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_backoff_resets_for_sent_and_received_traffic(self):
        client = python_client()
        batches, delays = [], []

        def serialize(batch):
            batches.append(list(batch))
            return b'test'

        client.serialize_messages = serialize
        client._blocking_http_req = lambda *args: b'' if len(batches) == 51 else b'response'
        client.deserialize_messages = lambda data: [object()] if len(batches) == 52 else [CheckInMessage()]

        async def wait(delay):
            delays.append(delay)
            if len(delays) == 50:
                await client.send_upstream_message(object())
            if len(delays) == 53:
                client.handle_checkout()

        client._wait_for_poll = wait
        with patch('random.random', return_value=0.5):
            await client.start()
        self.assertAlmostEqual(delays[0], 0.11)
        self.assertEqual(delays[49], 10.0)
        self.assertEqual(len(batches[50]), 2)
        self.assertAlmostEqual(delays[50], 0.1)  # Outbound activity, empty response.
        self.assertAlmostEqual(delays[51], 0.1)  # Inbound activity.
        self.assertAlmostEqual(delays[52], 0.11)  # Idle again.

    async def test_wait_wakes_for_data_checkout_and_transport_close(self):
        for action in ('send', 'checkout', 'close'):
            with self.subTest(action=action):
                client = python_client()
                waiter = asyncio.create_task(client._wait_for_poll(10))
                await asyncio.sleep(0)
                if action == 'send':
                    await client.send_upstream_message(object())
                elif action == 'checkout':
                    client.handle_checkout()
                else:
                    await client.close_transport()
                await asyncio.wait_for(waiter, timeout=0.5)

    async def test_pending_data_skips_wait_and_fixed_polling_keeps_its_interval(self):
        client = python_client()
        await client.send_upstream_message(object())
        client._poll_wake.clear()
        await asyncio.wait_for(client._wait_for_poll(10), timeout=0.5)

        client = python_client(fixed=True)
        waiter = asyncio.create_task(client._wait_for_poll(10))
        await asyncio.sleep(0)
        await client.send_upstream_message(object())
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        client.handle_checkout()
        await asyncio.wait_for(waiter, timeout=0.5)

    async def test_wait_cancellation_propagates(self):
        client = python_client()
        waiter = asyncio.create_task(client._wait_for_poll(10))
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter


class OtherClientPollingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required')
    def test_node_and_electron_polling(self):
        with tempfile.TemporaryDirectory() as temporary:
            for fixed in (False, True):
                for electron in (False, True):
                    with self.subTest(fixed=fixed, electron=electron):
                        path = Path(temporary) / 'client.js'
                        path.write_text(render_client('nodejs', fixed, electron), encoding='utf-8')
                        subprocess.run(['node', str(ROOT / 'tests/polling_node.js'), str(path)]
                                       + (['fixed'] if fixed else []), check=True, timeout=10)

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('MESSENGER_CSC'),
                         'Set MESSENGER_CSC to a .NET Framework-compatible Roslyn csc.exe')
    def test_csharp_polling(self):
        with tempfile.TemporaryDirectory() as temporary:
            for fixed in (False, True):
                with self.subTest(fixed=fixed):
                    source = Path(temporary) / 'HttpServiceClient.cs'
                    source.write_text(render_client('csharp', fixed), encoding='utf-8')
                    executable = Path(temporary) / 'polling.exe'
                    subprocess.run([os.environ['MESSENGER_CSC'], '/nologo', '/reference:System.Net.Http.dll',
                                    '/out:' + str(executable), str(source), str(ROOT / 'tests/polling_csharp.cs')],
                                   check=True, timeout=30)
                    subprocess.run([str(executable)] + (['fixed'] if fixed else []), check=True, timeout=10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
