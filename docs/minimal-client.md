# The Minimal Client

This guide walks through writing a Messenger client from scratch in Python. The result is a minimal WebSocket client that supports SOCKS and local port forwards (server-initiated TCP connections) -- no remote port forwards, no HTTP transport, no reconnection.

This is useful for understanding how the protocol works or for writing a client in a new language.

## What You Need

A minimal client must:
1. Connect via WebSocket and perform the CheckIn handshake
2. Run a send loop (single writer to the socket)
3. Receive and deserialize messages
4. Handle `InitiateTCPClientReq` -- connect to a destination and bridge data
5. Handle `SendDataMessage` -- forward data to/from TCP connections
6. Handle `CheckOutMessage` -- tear down and exit

## Full Implementation (~120 lines)

```python
import asyncio, hashlib, os, struct, base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import aiohttp

# -- Crypto --
def make_key(passphrase):
    return hashlib.sha256(passphrase.encode()).digest()

def encrypt(key, plaintext):
    iv = os.urandom(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return iv + cipher.encrypt(pad(plaintext, 16))

def decrypt(key, data):
    cipher = AES.new(key, AES.MODE_CBC, data[:16])
    return unpad(cipher.decrypt(data[16:]), 16)

# -- Wire format --
def pack_str(s):
    b = s.encode() if isinstance(s, str) else s
    return struct.pack('>I', len(b)) + b

def read_str(buf, off):
    length = struct.unpack('>I', buf[off:off+4])[0]
    return buf[off+4:off+4+length], off+4+length

def serialize(msg_type, payload, key):
    if msg_type not in (4, 7):  # not CheckIn/CheckOut
        payload = encrypt(key, payload)
    header = struct.pack('>II', msg_type, 8 + len(payload))
    return header + payload

def deserialize(data, key):
    msgs = []
    while len(data) >= 8:
        msg_type, msg_len = struct.unpack('>II', data[:8])
        if msg_len > len(data):
            break
        payload = data[8:msg_len]
        data = data[msg_len:]
        if msg_type not in (4, 7):
            payload = decrypt(key, payload)
        msgs.append((msg_type, payload))
    return msgs

# -- Message builders --
def checkin_msg(messenger_id, key):
    return serialize(4, pack_str(messenger_id), key)

def send_data_msg(client_id, data, key):
    payload = pack_str(client_id) + pack_str(base64.b64encode(data))
    return serialize(3, payload, key)

def tcp_client_rep(client_id, reason, key):
    payload = (pack_str(client_id) + pack_str('0.0.0.0') +
               struct.pack('>III', 0, 1, reason))
    return serialize(2, payload, key)

# -- Client --
class MinimalClient:
    def __init__(self, url, key):
        self.url = url
        self.key = key
        self.identifier = ''
        self.queue = asyncio.Queue()
        self.tcp_clients = {}  # client_id -> (reader, writer)

    async def run(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.url, ssl=False) as ws:
                self.ws = ws
                # CheckIn handshake
                await ws.send_bytes(checkin_msg('', self.key))
                resp = await ws.receive_bytes()
                msgs = deserialize(resp, self.key)
                _, payload = msgs[0]
                self.identifier, _ = read_str(payload, 0)
                self.identifier = self.identifier.decode()

                await asyncio.gather(self._send_loop(), self._recv_loop())

    async def _send_loop(self):
        while True:
            msg = await self.queue.get()
            batch = checkin_msg(self.identifier, self.key) + msg
            await self.ws.send_bytes(batch)

    async def _recv_loop(self):
        async for raw in self.ws:
            if raw.type != aiohttp.WSMsgType.BINARY:
                continue
            for msg_type, payload in deserialize(raw.data, self.key):
                if msg_type == 1:    # InitiateTCPClientReq
                    await self._handle_connect(payload)
                elif msg_type == 3:  # SendDataMessage
                    await self._handle_data(payload)
                elif msg_type == 7:  # CheckOut
                    return

    async def _handle_connect(self, payload):
        client_id, off = read_str(payload, 0)
        client_id = client_id.decode()
        dest_host, off = read_str(payload, off)
        dest_host = dest_host.decode()
        dest_port = struct.unpack('>I', payload[off:off+4])[0]
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(dest_host, dest_port), timeout=5)
            self.tcp_clients[client_id] = (r, w)
            await self.queue.put(tcp_client_rep(client_id, 0, self.key))
            asyncio.create_task(self._stream(client_id, r))
        except Exception:
            await self.queue.put(tcp_client_rep(client_id, 1, self.key))

    async def _handle_data(self, payload):
        client_id, off = read_str(payload, 0)
        client_id = client_id.decode()
        data_b64, _ = read_str(payload, off)
        data = base64.b64decode(data_b64)
        pair = self.tcp_clients.get(client_id)
        if not pair:
            return
        if not data:  # close signal
            pair[1].close()
            self.tcp_clients.pop(client_id, None)
            return
        pair[1].write(data)

    async def _stream(self, client_id, reader):
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                await self.queue.put(
                    send_data_msg(client_id, data, self.key))
        except Exception:
            pass
        finally:
            self.tcp_clients.pop(client_id, None)
            await self.queue.put(
                send_data_msg(client_id, b'', self.key))

if __name__ == '__main__':
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else 'ws://localhost:8080'
    passphrase = sys.argv[2] if len(sys.argv) > 2 else 'test'
    client = MinimalClient(url, make_key(passphrase))
    asyncio.run(client.run())
```

## What This Supports

- WebSocket transport
- CheckIn handshake (ID assignment)
- Server-initiated TCP connections (SOCKS and local port forwards work)
- Bidirectional data forwarding
- Close signals (empty SendData)
- CheckOut (kill)

## What This Does NOT Support

- HTTP polling transport
- Remote port forwards (`InitiateBINDReq`/`InitiateBINDRep`)
- Reconnection logic
- Runtime argument parsing (`--server-url`, etc.)
- Output suppression (`--no-print`)
- Message batching (sends one message at a time)

## Adding Remote Port Forwards

To support remote port forwards, you need to:
1. Handle `InitiateBINDReq` -- bind a TCP listener and reply with `InitiateBINDRep`
2. On accepted connections, send `InitiateTCPClientReq` with the listening endpoint
3. Handle `InitiateTCPClientRep` -- start streaming on success, close on failure
4. Handle the stop signal (empty listening host in `InitiateBINDReq`)

See [client.pseudo](client.pseudo) for the full specification.
