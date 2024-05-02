import argparse
import asyncio
import base64
import collections
import json
import random
import socket
import ssl
import sys

from urllib import request

try:
    import aiohttp
except ImportError:
    print('Failed to import aiohttp module.')


BUFFER_SIZE = 4096
HTTP_ROUTE = 'http'
WS_ROUTE = 'ws'


class MessengerClient:
    NAME = 'MessengerClient'
    CLIENT = collections.namedtuple('Client', 'reader writer')

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
        return json.dumps({
            'identifier': identifier,
            'msg': self.bytes_to_base64(msg),
        })

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
        atype = msg.get('atype')
        address = msg.get('address')
        port = int(msg.get('port'))
        try:
            reader, writer = await asyncio.open_connection(address, port)
            self.clients[msg.get('identifier')] = self.CLIENT(reader, writer)
            bind_addr, bind_port = writer.get_extra_info('sockname')
            return self.socks_connect_results(identifier, 0, atype, bind_addr, bind_port)
        except Exception as e:  #ToDo add more exceptions and update the rep.
            return self.socks_connect_results(identifier, 1, atype, None, None)

    def stream(self, identifier, transport):
        return NotImplementedError(f'{self.NAME} does not implement stream')


class WebSocketMessengerClient(MessengerClient):

    def __init__(self, uri, buffer_size):
        super().__init__(uri, buffer_size)

    async def connect(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.uri, ssl=self.ssl_context) as ws:
                async for msg in ws:
                    msg = json.loads(msg.data)
                    identifier = msg.get('identifier', None)
                    if not identifier:
                        return
                    if identifier in self.clients:
                        self.clients[identifier].writer.write(self.base64_to_bytes(msg.get('msg')))
                        continue
                    await ws.send_str(await self.socks_connect(identifier, msg))
                    asyncio.create_task(self.stream(identifier, ws))

    async def stream(self, identifier, ws):
        client = self.clients[identifier]
        while True:
            msg = await client.reader.read(self.buffer_size)
            if not msg:
                break
            downstream_msg = self.generate_downstream_msg(identifier, msg)
            await ws.send_str(downstream_msg)


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
        while True:
            await asyncio.sleep(0.1)
            downstream_data = []
            while not self.downstream.empty():
                data = await self.downstream.get()
                downstream_data.append(data)
            if len(downstream_data) == 0:
                downstream_data.append(check_in)
            retrieve_data = request.Request(self.uri, data=json.dumps(downstream_data).encode('utf-8'), method='POST')
            with request.urlopen(retrieve_data, context=self.ssl_context) as response:
                messages = json.loads(response.read().decode('utf-8'))
                for msg in messages:
                    msg = json.loads(msg)
                    identifier = msg.get('identifier', None)
                    if not identifier:
                        continue
                    if identifier in self.clients:
                        self.clients[identifier].writer.write(self.base64_to_bytes(msg.get('msg')))
                        continue
                    socks_connect_results = await self.socks_connect(f'{self.socks_server_id}:{identifier}', msg)
                    await self.downstream.put(socks_connect_results)
                    asyncio.create_task(self.stream(identifier, 'http'))

    async def stream(self, identifier, _):
        client = self.clients[identifier]
        while True:
            msg = await client.reader.read(self.buffer_size)
            if not msg:
                break
            downstream_msg = self.generate_downstream_msg(f'{self.socks_server_id}:{identifier}', msg)
            await self.downstream.put(downstream_msg)


async def main(args):
    try:
        messenger_client = WebSocketMessengerClient(f'{args.uri}{WS_ROUTE}', BUFFER_SIZE)
        await messenger_client.connect()
        sys.exit(0)
    except Exception as e:
        print(f'Failed to connect to MessengerServer over WS: {e}')

    try:
        messenger_client = HTTPMessengerClient(f'{args.uri}{HTTP_ROUTE}', BUFFER_SIZE)
        await messenger_client.connect()
        sys.exit(0)
    except Exception as e:
        print(f'Failed to connect to MessengerServer over HTTP: {e}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('uri', type=str)
    args = parser.parse_args()
    asyncio.run(main(args))
