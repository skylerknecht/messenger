import ssl
import sys
import traceback

from aiohttp import web

from messenger.messengers import HTTPMessenger, WebSocketMessenger

class HTTPWSServer:
    def __init__(self, update_cli, messenger_engine, ip: str = '127.0.0.1', port: int = 1337, ssl: tuple = None):
        # Server Settings
        self.ip = ip
        self.port = port
        self.ssl = ssl

        # Manager Utilities
        self.update_cli = update_cli
        self.messenger_engine = messenger_engine

    async def start(self):
        app = web.Application(client_max_size=2 * 1024 * 1024 * 1024)  # 2 GB
        app.on_response_prepare.append(self.remove_server_header)
        app.router.add_routes([
            web.route('*', '/{tail:.*}', self.redirect_handler)
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            if self.ssl:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(self.ssl[0], self.ssl[1])
                site = web.TCPSite(runner, self.ip, self.port, ssl_context=ssl_context)
                await site.start()
            else:
                site = web.TCPSite(runner, self.ip, self.port)
                await site.start()
            self.update_cli.display(f"Waiting for messengers on http{'s' if self.ssl else ''}+ws{'s' if self.ssl else ''}://{self.ip}:{self.port}/", 'Information', reprompt=False)
        except OSError:
            self.update_cli.display(f'An error prevented the server from starting:\n{traceback.format_exc()}', 'error', reprompt=False)
            sys.exit(1)

    @staticmethod
    async def remove_server_header(_, response):
        if 'Server' in response.headers:
            del response.headers['Server']

    async def redirect_handler(self, request):
        transport = request.query.get('transport', None)
        if not transport:
            return web.Response(status=404, text='Not Found')
        elif transport == 'websocket':
            return await self.websocket_handler(request)
        elif transport == 'polling' and request.method == 'POST':
            return await self.http_post_handler(request)
        else:
            return web.Response(status=404, text='Not Found')

    async def http_post_handler(self, request):
        # Retrieve metadata about the request
        ip = request.remote
        user_agent = request.headers.get('User-Agent', 'Unknown')

        upstream_message_data = b''
        data = await request.read()
        messages = self.messenger_engine.deserialize_messages(data)
        messenger_id = self.messenger_engine.get_messenger_id(messages[0])
        if not messenger_id:
            http_messenger = HTTPMessenger(ip, user_agent, self.update_cli, self.messenger_engine.serialize_messages)
            check_in_message = self.messenger_engine.add_messenger(http_messenger)
            upstream_message_data += check_in_message
        else:
            upstream_message_data += await self.messenger_engine.send_messages(messenger_id, messages[1:])

        return web.Response(status=200, body=upstream_message_data)

    async def websocket_handler(self, request):
        # Prepare the WebSocket handshake

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        ip = request.remote
        user_agent = request.headers.get('User-Agent', 'Unknown')
        ws_messenger = WebSocketMessenger(
            ws,
            ip,
            user_agent,
            self.update_cli,
            self.messenger_engine.serialize_messages
        )
        check_in_message = self.messenger_engine.add_messenger(ws_messenger)
        await ws.send_bytes(check_in_message)

        async for msg in ws:
            # 1) Deserialize all messages from this binary frame
            messages = self.messenger_engine.deserialize_messages(msg.data)
            # 2) Identify the messenger (if any) from the first message
            messenger_id = self.messenger_engine.get_messenger_id(messages[0])

            # 3b) Send the subsequent messages to the existing Messenger
            await self.messenger_engine.send_messages(
                messenger_id,
                messages[1:]
            )

        if ws_messenger:
            ws_messenger.alive = False

        return ws