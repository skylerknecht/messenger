import ssl
import json
import time

from aiohttp import web
from messenger.messengers import HTTPMessenger, WSMessenger
from messenger.message import MessageBuilder, MessageParser

class Server:
    def __init__(self, messengers, update_cli, address: str = '127.0.0.1', port: int = 1337, ssl: tuple = None):
        self.messengers = messengers
        self.update_cli = update_cli
        self.address = address
        self.port = port
        self.ssl = ssl
        self.app = web.Application()
        self.app.on_response_prepare.append(self.remove_server_header)
        self.app.router.add_routes([
            web.route('*', '/{tail:.*}', self.redirect_handler)
        ])

    async def http_get_handler(self, request):
        messenger = HTTPMessenger(self.update_cli)
        self.messengers.append(messenger)
        self.update_cli.display(f'{messenger.transport} Messenger {id(messenger)} has successfully connected.', 'success')
        return web.Response(status=200, text=str(id(messenger)))

    async def http_post_handler(self, request):
        # Read the binary data from the request
        data = await request.read()
        # Parse the binary blob into individual messages
        downstream_messages = MessageParser.parse_messages(data)
        upstream_messages = b''
        check_in_message = downstream_messages[0]
        messenger_id = check_in_message.get('Messenger ID')
        if not messenger_id:
            return web.Response(status=404, text=f'Not Found')
        for messenger in self.messengers:
            if str(id(messenger)) == messenger_id:
                upstream_messages += await messenger.get_upstream_messages()
                for downstream_message in downstream_messages[1:]:
                    await messenger.handle_message(downstream_message)
                break
        else:
            self.update_cli.display(f'Messenger {messenger_id} not found, discarding {len(downstream_messages)} message(s)!', 'error')
            return web.Response(status=404, text=f'Not Found')
        return web.Response(status=200, body=upstream_messages)

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
        print(f"Waiting for messengers on http{'s' if self.ssl else ''}+ws{'s' if self.ssl else ''}://{self.address}:{self.port}/")

    async def websocket_handler(self, request):
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        messenger = WSMessenger(websocket, self.update_cli)
        self.messengers.append(messenger)
        self.update_cli.display(f'{messenger.transport} Messenger {id(messenger)} has successfully connected.', 'success')
        async for downstream_message in websocket:
            messages = MessageParser.parse_messages(downstream_message.data)
            for message in messages:
                await messenger.handle_message(message)

        messenger.alive = False
        return websocket

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