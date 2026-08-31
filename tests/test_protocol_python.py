import asyncio
import hashlib
import struct
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "builder/clients/python/templates/messenger-client.py"


def load_client_module():
    """Load the client classes without Jinja2 or running main()."""
    source = TEMPLATE.read_text(encoding="utf-8").split("## Arg Parsing", 1)[0]
    source = source.replace('"{{ server_url }}"', '"http://127.0.0.1"')
    source = source.replace('"{{ encryption_key }}"', '"test-key"')
    source = source.replace('"{{ user_agent }}"', '"test-agent"')
    source = source.replace('"{{ proxy }}"', '""')
    source = source.replace("{{ retry_duration }}", "1.0")
    source = source.replace("{{ retry_attempts }}", "1")
    module = types.ModuleType("messenger_client_under_test")
    exec(compile(source, str(TEMPLATE), "exec"), module.__dict__)
    return module


M = load_client_module()
KEY = hashlib.sha256(b"test-key").digest()


def checkout_frame():
    return struct.pack("!II", 0x07, 8)


class FakeTransport:
    def __init__(self):
        self.paused = False

    def pause_reading(self):
        self.paused = True

    def resume_reading(self):
        self.paused = False


class FakeWriter:
    def __init__(self):
        self.transport = FakeTransport()
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(bytes(data))

    def close(self):
        self.closed = True


class EOFReader:
    async def read(self, _size):
        return b""


class FailingWebSocket:
    async def send_bytes(self, _data):
        raise ConnectionError("injected send failure")


class RecordingWebSocket:
    def __init__(self):
        self.sent = []

    async def send_bytes(self, data):
        self.sent.append(bytes(data))


class RecordingClient(M.Client):
    def __init__(self):
        super().__init__(KEY)
        self.sent = []

    async def send_upstream_message(self, message):
        self.sent.append(message)

    async def close_transport(self):
        pass


class PythonReachableMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_concatenated_server_messages_preserve_order(self):
        client = RecordingClient()
        raw = client.serialize_messages([
            M.CheckInMessage("client-1"),
            M.InitiateBINDReq("B", "127.0.0.1", 0, "127.0.0.1", 80),
        ]) + checkout_frame()
        messages = client.deserialize_messages(raw)
        self.assertEqual(
            [type(message).__name__ for message in messages],
            ["CheckInMessage", "InitiateBINDReq", "CheckOutMessage"],
        )

    async def test_decryption_error_propagates(self):
        client = RecordingClient()
        raw = bytearray(client.serialize_messages([M.SendDataMessage("T", b"hello")]))
        raw[-1] ^= 0xFF
        with self.assertRaises(M.DecryptionError):
            client.deserialize_messages(bytes(raw))

    async def test_data_then_empty_data_closes_only_matching_connection(self):
        client = RecordingClient()
        writer = FakeWriter()
        other = FakeWriter()
        client.tcp_clients["T"] = M.TcpClient(None, writer, None)
        client.tcp_clients["OTHER"] = M.TcpClient(None, other, None)

        await client.dispatch_message(M.SendDataMessage("T", b"abc"))
        self.assertEqual(writer.writes, [b"abc"])
        await client.dispatch_message(M.SendDataMessage("T", b""))

        self.assertTrue(writer.closed)
        self.assertNotIn("T", client.tcp_clients)
        self.assertIn("OTHER", client.tcp_clients)

    async def test_unknown_late_data_is_ignored(self):
        client = RecordingClient()
        await client.dispatch_message(M.SendDataMessage("missing", b"late"))
        self.assertEqual(client.tcp_clients, {})

    async def test_failed_tcp_reply_closes_waiting_rpf_socket(self):
        client = RecordingClient()
        writer = FakeWriter()
        client.tcp_clients["T"] = M.TcpClient(EOFReader(), writer, "B")

        await client.dispatch_message(M.InitiateTCPClientRep(
            "T", "0.0.0.0", 0, 1, 5, "", 0
        ))

        self.assertTrue(writer.closed)
        self.assertNotIn("T", client.tcp_clients)

    async def test_successful_tcp_reply_resumes_then_streams(self):
        client = RecordingClient()
        writer = FakeWriter()
        writer.transport.paused = True
        client.tcp_clients["T"] = M.TcpClient(EOFReader(), writer, "B")

        await client.dispatch_message(M.InitiateTCPClientRep(
            "T", "0.0.0.0", 0, 1, 0, "", 0
        ))
        for _ in range(20):
            if "T" not in client.tcp_clients:
                break
            await asyncio.sleep(0)

        self.assertFalse(writer.transport.paused)
        self.assertTrue(writer.closed)
        self.assertTrue(any(
            isinstance(message, M.SendDataMessage) and message.client_id == "T" and message.data == b""
            for message in client.sent
        ))

    async def test_real_bind_then_same_id_stop_finishes_stopped(self):
        client = RecordingClient()
        start = M.InitiateBINDReq("B", "127.0.0.1", 0, "127.0.0.1", 80)
        stop = M.InitiateBINDReq("B", "", 0, "", 0)

        await client.handle_bind(start)
        self.assertEqual(len(client.remote_port_forwarders), 1)
        owned = FakeWriter()
        unrelated = FakeWriter()
        client.tcp_clients["owned"] = M.TcpClient(EOFReader(), owned, "B")
        client.tcp_clients["other"] = M.TcpClient(EOFReader(), unrelated, "OTHER")
        await client.handle_bind(stop)
        for _ in range(20):
            if not client.remote_port_forwarders:
                break
            await asyncio.sleep(0)
        self.assertEqual(client.remote_port_forwarders, [])
        self.assertTrue(owned.closed)
        self.assertFalse(unrelated.closed)
        self.assertNotIn("owned", client.tcp_clients)
        self.assertIn("other", client.tcp_clients)

    async def test_checkout_overrides_mixed_http_batch(self):
        client = M.HTTPClient("http://127.0.0.1", KEY, "test-agent", None)
        bind = client.serialize_messages([
            M.InitiateBINDReq("B", "127.0.0.1", 0, "127.0.0.1", 80)
        ])
        client._blocking_http_req = lambda request, timeout=10.0: bind + checkout_frame()

        await asyncio.wait_for(client.start(), timeout=1)
        self.assertTrue(client.killed)
        self.assertEqual(client.remote_port_forwarders, [])

    async def test_known_id_http_reconnect_dispatches_queued_checkout(self):
        """A reconnect response is part of the reachable server protocol."""
        client = M.HTTPClient("http://127.0.0.1", KEY, "test-agent", None)
        client.identifier = "known-id"
        client._blocking_http_req = lambda request, timeout=10.0: checkout_frame()

        await client.connect()
        self.assertTrue(
            client.killed,
            "known-ID connect ignored the server response containing queued Checkout",
        )

    async def test_websocket_pending_batch_survives_send_failure(self):
        client = M.WSClient("ws://127.0.0.1", KEY, "test-agent", None)
        client.identifier = "known-id"
        message = M.SendDataMessage("T", b"ordered")
        await client.send_upstream_message(message)
        client.ws = FailingWebSocket()

        await client._send_loop()
        self.assertEqual(client._pending, [message])

        replacement = RecordingWebSocket()
        client.ws = replacement
        sender = asyncio.create_task(client._send_loop())
        for _ in range(20):
            if replacement.sent:
                break
            await asyncio.sleep(0)
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)

        self.assertEqual(client._pending, [])
        parsed = client.deserialize_messages(replacement.sent[0])
        self.assertEqual([type(item).__name__ for item in parsed], ["CheckInMessage", "SendDataMessage"])
        self.assertEqual(parsed[1].data, b"ordered")


if __name__ == "__main__":
    unittest.main(verbosity=2)
