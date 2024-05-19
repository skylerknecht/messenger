import argparse
import asyncio
import base64
import json
import random
import socket
import ssl
import sys
import urllib
import traceback

from urllib import request

try:
    import aiohttp
except ImportError:
    print('Failed to import aiohttp module.')

BUFFER_SIZE = 4096
HTTP_ROUTE = 'socketio/?EIO=4&transport=polling'
WS_ROUTE = 'socketio/?EIO=4&transport=websocket'


class Client:

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer


class MessengerClient:
    NAME = 'MessengerClient'

    def __init__(self, uri, buffer_size):
        self.uri = uri
        self.buffer_size = buffer_size
        self.clients = {}
        # Accept Self Signed SSL Certs
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    @staticmethod
    def bytes_to_base64(data) -> str:
        """
        Base64 encode a bytes object.
        :param data: A python bytes object.
        :return: A base64 encoded string
        :rtype: str
        """
        return base64.b64encode(data).decode('utf-8')

    @staticmethod
    def base64_to_bytes(data) -> bytes:
        """
        Base64 encode a bytes object.
        :param data: A base64 string.
        :return: A bytes object.
        :rtype: bytes
        """
        return base64.b64decode(data)

    def connect(self):
        return NotImplementedError(f'{self.NAME} does not implement stream')

    def generate_downstream_msg(self, identifier, msg: bytes):
        return {
            'identifier': identifier,
            'msg': self.bytes_to_base64(msg),
        }

    def socks_connect_results(self, identifier, rep, atype, bind_addr, bind_port):
        return self.generate_downstream_msg(
            identifier,
            b''.join([
                b'\x05',
                int(rep).to_bytes(1, 'big'),
                int(0).to_bytes(1, 'big'),
                int(1).to_bytes(1, 'big'),
                socket.inet_aton(bind_addr) if bind_addr else int(0).to_bytes(1, 'big'),
                bind_port.to_bytes(2, 'big') if bind_port else int(0).to_bytes(1, 'big')
            ])
        )

    async def socks_connect(self, identifier, msg):
        return NotImplementedError(f'{self.NAME} does not implement socks_connect')

    async def stream(self, identifier):
        return NotImplementedError(f'{self.NAME} does not implement stream')


class WebSocketMessengerClient(MessengerClient):

    def __init__(self, uri, buffer_size):
        super().__init__(uri, buffer_size)
        self.ws = None

    async def connect(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.uri, ssl=self.ssl_context) as ws:
                self.ws = ws
                print(f'[+] Successfully connected to {self.uri}')
                async for msg in ws:
                    msg = msg.json()
                    identifier = msg.get('identifier', None)
                    if not identifier:
                        continue
                    if identifier not in self.clients and msg.get('atype'):
                        asyncio.create_task(self.socks_connect(identifier, msg))
                        continue
                    if not msg.get('msg'):
                        continue
                    msg = self.base64_to_bytes(msg.get('msg'))
                    if msg == b'' and identifier in self.clients:
                        self.clients[identifier].writer.close()
                        continue
                    if identifier in self.clients:
                        self.clients[identifier].writer.write(msg)
                        continue

    async def socks_connect(self, identifier, msg):
        atype = msg.get('atype')
        address = msg.get('address')
        port = int(msg.get('port'))
        try:
            reader, writer = await asyncio.open_connection(address, port)
            self.clients[msg.get('identifier')] = Client(reader, writer)
            bind_addr, bind_port = writer.get_extra_info('sockname')
            await self.ws.send_json(self.socks_connect_results(identifier, 0, atype, bind_addr, bind_port))
            asyncio.create_task(self.stream(identifier))
        except Exception as e:  #ToDo add more exceptions and update the rep.
            await self.ws.send_json(self.socks_connect_results(identifier, 1, atype, None, None))

    async def stream(self, identifier):
        client = self.clients[identifier]
        while True:
            try:
                msg = await client.reader.read(self.buffer_size)
                if not msg:
                    break
                downstream_msg = self.generate_downstream_msg(identifier, msg)
                await self.ws.send_json(downstream_msg)
            except (EOFError, ConnectionResetError):
                # ToDo add debug statement
                # output.display(f"Client {self.identifier} disconnected unexpectedly")
                break
        downstream_msg = self.generate_downstream_msg(identifier, b'')
        await self.ws.send_json(downstream_msg)
        del self.clients[identifier]


class HTTPMessengerClient(MessengerClient):
    def __init__(self, uri, buffer_size):
        super().__init__(uri, buffer_size)
        self.socks_server_id = None
        self.downstream = asyncio.Queue()

    async def connect(self):
        with request.urlopen(self.uri, context=self.ssl_context) as response:
            self.socks_server_id = response.read().decode('utf-8')
        check_in = self.generate_downstream_msg(
            f'{self.socks_server_id}:',
            bytes([random.randint(100, 252), random.randint(100, 252), random.randint(100, 252)])
        )
        print(f'[+] Successfully connected to {self.uri}')
        while True:
            await asyncio.sleep(0.1)
            downstream_data = []
            while not self.downstream.empty() and len(downstream_data) < 10:
                downstream_data.append(await self.downstream.get())
            if not downstream_data:
                downstream_data.append(check_in)
            retrieve_data = request.Request(self.uri, data=json.dumps(downstream_data).encode('utf-8'), method='POST')
            retrieve_data.add_header('Content-Type', 'application/json')
            with request.urlopen(retrieve_data, context=self.ssl_context) as response:
                messages = json.loads(response.read().decode('utf-8'))
                if response.status != 200:
                    break
                for msg in messages:
                    msg = json.loads(msg)
                    identifier = msg.get('identifier', None)
                    if not identifier:
                        continue
                    if identifier not in self.clients and msg.get('atype'):
                        asyncio.create_task(self.socks_connect(identifier, msg))
                        continue
                    if not msg.get('msg'):
                        continue
                    msg = self.base64_to_bytes(msg.get('msg'))
                    if msg == b'close' and identifier in self.clients:
                        self.clients[identifier].writer.close()
                        continue
                    if identifier in self.clients:
                        self.clients[identifier].writer.write(msg)
                        continue

    async def socks_connect(self, identifier, msg):
        atype = msg.get('atype')
        address = msg.get('address')
        port = int(msg.get('port'))
        try:
            reader, writer = await asyncio.open_connection(address, port)
            self.clients[msg.get('identifier')] = Client(reader, writer)
            bind_addr, bind_port = writer.get_extra_info('sockname')
            await self.downstream.put(self.socks_connect_results(f'{self.socks_server_id}:{identifier}', 0, atype, bind_addr, bind_port))
            asyncio.create_task(self.stream(identifier))
        except Exception as e:  #ToDo add more exceptions and update the rep.
            await self.downstream.put(self.socks_connect_results(f'{self.socks_server_id}:{identifier}', 1, atype, None, None))

    async def stream(self, identifier):
        client = self.clients[identifier]
        while True:
            try:
                msg = await client.reader.read(self.buffer_size)
                if not msg:
                    break
                downstream_msg = self.generate_downstream_msg(f'{self.socks_server_id}:{identifier}', msg)
                await self.downstream.put(downstream_msg)
            except (EOFError, ConnectionResetError):
                # ToDo add debug statement
                # output.display(f"Client {self.identifier} disconnected unexpectedly")
                break
        downstream_msg = self.generate_downstream_msg(f'{self.socks_server_id}:{identifier}', b'')
        await self.downstream.put(downstream_msg)
        del self.clients[identifier]


async def try_http(url):
    try:
        messenger_client = HTTPMessengerClient(f'{url}{HTTP_ROUTE}', BUFFER_SIZE)
        await messenger_client.connect()
        return True
    except Exception as e:
        print(f'[!] Failed to connect to {url}')
        return False


async def try_ws(url):
    try:
        messenger_client = WebSocketMessengerClient(f'{url}{WS_ROUTE}', BUFFER_SIZE)
        await messenger_client.connect()
        return True
    except Exception as e:
        print(f'[!] Failed to connect to {url}')
        return False


async def main(args):
    uri = args.uri.strip('/')
    attempts = []

    if "://" in uri:
        scheme, uri = uri.split("://", 1)
        attempts = scheme.split('+')
    else:
        attempts = ["ws", "http", "wss", "https"]

    for attempt in attempts:
        attempt_url = f"{attempt}://{uri}/"
        if "http" in attempt:
            success = await try_http(attempt_url)
            if success:
                sys.exit(0)
        elif "ws" in attempt:
            success = await try_ws(attempt_url)
            if success:
                sys.exit(0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('uri', type=str)
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print('\rMessenger Client stopped.')










