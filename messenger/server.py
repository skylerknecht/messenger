import asyncio
import ssl
import random
import json

from aiohttp import web
from .socks import SocksServer


class MessengerServer:
    def __init__(self, address: str = '127.0.0.1', port: int = 1337,
                 http_route: str = '/http',
                 ws_route: str = '/ws',
                 ssl: tuple[str, str] = None,
                 buffer_size: int = 4096):
        self.address = address
        self.port = port
        self.ssl = ssl
        self.buffer_size = buffer_size
        self.app = web.Application()
        self.app.router.add_routes([
            web.get(http_route, self.http_get_handler),
            web.post(http_route, self.http_post_handler),
        ])
        self.app.router.add_routes([
            web.get(ws_route, self.websocket_handler),
        ])
        self.socks_servers = []

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        if self.ssl:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self.ssl[0], self.ssl[1])
            site = web.TCPSite(runner, self.address, self.port, ssl_context=ssl_context)
            await site.start()
        else:
            site = web.TCPSite(runner, self.address, self.port)
            await site.start()
        print(f"Messenger Server is running on http{'s' if self.ssl else ''}://{self.address}:{self.port}/")

    async def http_get_handler(self, request):
        port = random.randint(9050, 9100)
        socks_server = SocksServer(('127.0.0.1', port), buffer_size=self.buffer_size)
        self.socks_servers.append(socks_server)
        await socks_server.start()
        print('HTTP Socks Server started on {}'.format(port))
        return web.Response(status=200, text=str(id(socks_server)))

    async def http_post_handler(self, request):
        messages = json.loads(await request.text())
        upstream_data = []
        for msg in messages:
            msg = json.loads(msg)
            identifier = msg.get('identifier', None)
            msg = msg.get('msg', None)
            if not identifier:
                return web.Response(status=404, text='Not Found')
            if not msg:
                return web.Response(status=404, text='Not Found')
            socks_server_identifier, client_identifier = identifier.split(':')
            for socks_server in self.socks_servers:
                if id(socks_server) == int(socks_server_identifier):
                    for client in socks_server.clients:
                        while not client.upstream.empty():
                            data = await client.upstream.get()
                            upstream_data.append(data)
                    if not client_identifier:
                        continue
                    socks_server.send_downstream(client_identifier, msg)
        return web.Response(status=200, text=json.dumps(upstream_data))

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        port = random.randint(9050, 9100)
        socks_server = SocksServer(('127.0.0.1', port), transport=ws, buffer_size=self.buffer_size)
        self.socks_servers.append(socks_server)
        await socks_server.start()
        print('Websocket Socks Server started on {}'.format(port))

        async for msg in ws:
            msg = json.loads(msg.data)
            identifier = msg.get('identifier', None)
            msg = msg.get('msg', None)
            if not identifier:
                return ws
            if not msg:
                return ws
            socks_server.send_downstream(identifier, msg)

        self.socks_servers.remove(socks_server)
        print('socks server stopped on {}'.format(port))
        return ws

