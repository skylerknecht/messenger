import ssl
import json
import time

from aiohttp import web
from messenger.socks import SocksServer


class MessengerServer:
    def __init__(self, address: str = '127.0.0.1', port: int = 1337, ssl: tuple = None, buffer_size: int = 4096):
        self.address = address
        self.port = port
        self.ssl = ssl
        self.buffer_size = buffer_size
        self.app = web.Application()
        self.app.on_response_prepare.append(self.remove_server_header)
        self.app.router.add_routes([
            web.route('*', '/{tail:.*}', self.redirect_handler)
        ])
        self.socks_servers = []

    @staticmethod
    async def remove_server_header(request, response):
        if 'Server' in response.headers:
            del response.headers['Server']

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
        print(f"Messenger Server is running on http{'s' if self.ssl else ''}+ws{'s' if self.ssl else ''}://{self.address}:{self.port}/")

    async def http_get_handler(self, request):
        socks_server = SocksServer(buffer_size=self.buffer_size)
        self.socks_servers.append(socks_server)
        await socks_server.start()
        return web.Response(status=200, text=str(id(socks_server)))

    async def http_post_handler(self, request):
        messages = await request.json()
        upstream_data = []
        for msg in messages:
            identifier = msg.get('identifier', None)
            msg = msg.get('msg', None)
            if not identifier:
                return web.Response(status=404, text='Not Found')
            socks_server_identifier, client_identifier = identifier.split(':')
            current_socks_server = None
            for socks_server in self.socks_servers:
                if id(socks_server) == int(socks_server_identifier):
                    current_socks_server = socks_server
            if not current_socks_server:
                return web.Response(status=404, text='Not Found')
            if current_socks_server.is_stopped():
                return web.Response(status=404, text='Not Found')
            current_socks_server.last_check_in = time.time()
            for client in current_socks_server.clients:
                while not client.upstream.empty():
                    data = await client.upstream.get()
                    upstream_data.append(data)
            if not client_identifier:
                continue
            current_socks_server.send_downstream(client_identifier, msg)
        return web.Response(status=200, text=json.dumps(upstream_data))

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        socks_server = SocksServer(transport=ws, buffer_size=self.buffer_size)
        self.socks_servers.append(socks_server)
        await socks_server.start()

        async for msg in ws:
            msg = json.loads(msg.data)
            identifier = msg.get('identifier', None)
            msg = msg.get('msg', None)
            if not identifier:
                continue
            if not msg:
                continue
            if socks_server.is_stopped():
                break
            socks_server.send_downstream(identifier, msg)

        await socks_server.stop()
        return ws

    async def redirect_handler(self, request):
        transport = request.query.get('transport', None)
        if not transport:
            return web.Response(status=404, text='Not Found')
        elif transport == 'websocket':
            return await self.websocket_handler(request)
        elif transport == 'polling' and request.method == 'GET':
            return await self.http_get_handler(request)
        elif transport == 'polling' and request.method == 'POST':
            return await self.http_post_handler(request)
        else:
            return web.Response(status=404, text='Not Found')
