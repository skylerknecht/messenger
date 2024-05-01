import asyncio
import ssl
import random
import json

from aiohttp import web
from .socks import SocksServer


class MessengerServer:
    def __init__(self, address: str = '127.0.0.1', port: int = 1337, http_route: str = '/http', ws_route: str = '/ws',
                 ssl: tuple[str, str] = None):
        self.address = address
        self.port = port
        self.ssl = ssl
        self.app = web.Application()
        self.app.router.add_routes([
            web.get(http_route, self.http_handler),
            web.post(http_route, self.http_handler),
        ])
        self.app.router.add_routes([
            web.get(ws_route, self.http_handler),
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
        site = web.TCPSite(runner, self.address, self.port)
        await site.start()
        await asyncio.Event().wait()
        print('Server running on {}:{}'.format(self.address, self.port))

    async def http_handler(self, request):
        if request.method == 'GET':
            port = random.randint(9050, 9100)
            socks_server = SocksServer(('127.0.0.1', port))
            self.socks_servers.append(socks_server)
            await socks_server.start()
            print('socks server started on {}'.format(port))
            return web.Response(status=200, text=str(id(socks_server)))
        elif request.method == 'POST':
            data = await request.json()
            print(data)
            if len(data) != 10:
                identifier = json.loads(data).get('identifier', None)
                if identifier:
                    for socks_server in self.socks_servers:
                        socks_server.send_downstream(data)
                    return web.Response(status=200, text='gotchu')
            upstream_data = []
            for socks_server in self.socks_servers:
                if id(socks_server) != int(data):
                    continue
                for client in socks_server.clients:
                    while not client.upstream.empty():
                        data = await client.upstream.get()
                        upstream_data.append(data)
            return web.Response(status=200, text=json.dumps(upstream_data))
        else:
            return web.Response(status=405, text='Method Not Allowed')

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        port = random.randint(9050, 9100)
        socks_server = SocksServer(('127.0.0.1', port), transport=ws)
        self.socks_servers.append(socks_server)
        await socks_server.start()
        print('socks server started on {}'.format(port))

        async for msg in ws:
            socks_server.send_downstream(msg.data)

        self.socks_servers.remove(socks_server)
        print('socks server stopped on {}'.format(port))
        return ws

