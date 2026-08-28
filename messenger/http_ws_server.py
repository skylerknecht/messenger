import ssl
import traceback

from aiohttp import web


class HTTPWSServer:
    def __init__(self, update_cli, messenger_engine, ip: str = '127.0.0.1', port: int = 1337, ssl_cert: tuple = None):
        self.ip = ip
        self.port = port
        self.ssl_cert = ssl_cert
        self.update_cli = update_cli
        self.engine = messenger_engine

    async def start(self):
        app = web.Application()
        app.on_response_prepare.append(self.remove_server_header)
        app.router.add_routes([
            web.route('*', '/{tail:.*}', self.redirect_handler)
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            if self.ssl_cert:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(self.ssl_cert[0], self.ssl_cert[1])
                site = web.TCPSite(runner, self.ip, self.port, ssl_context=ssl_context)
                await site.start()
            else:
                site = web.TCPSite(runner, self.ip, self.port)
                await site.start()
            self.update_cli.display(f"Waiting for messengers on http{'s' if self.ssl_cert else ''}+ws{'s' if self.ssl_cert else ''}://{self.ip}:{self.port}/", 'information', reprompt=False, display_module='handlers')
        except OSError:
            self.update_cli.display(f'An error prevented the server from starting:\n{traceback.format_exc()}', 'error', reprompt=False, display_module='handlers')

    @staticmethod
    async def remove_server_header(_, response):
        if 'Server' in response.headers:
            del response.headers['Server']

    async def redirect_handler(self, request):
        self.update_cli.display(
            f'The handler received a {request.method} from {request.remote}.',
            'debug', display_module='handlers',
        )
        upgrade = request.headers.get('Upgrade', '').lower()
        if upgrade == 'websocket':
            return await self.websocket_handler(request)
        if request.method == 'POST':
            return await self.http_post_handler(request)
        return web.Response(status=404, text='Not Found')

    async def http_post_handler(self, request):
        data = await request.read()
        try:
            messenger = await self.engine.checkin_http(
                data, request.remote, request.headers.get('User-Agent', '•••')
            )
        except Exception as e:
            self.update_cli.display(f'Error processing check in: {e}', 'warning', display_module='handlers')
            return web.Response(status=200, body=b'')
        if not messenger:
            return web.Response(status=200, body=b'')
        return web.Response(status=200, body=await self.engine.get_downstream_messages(messenger))

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        msg = await ws.receive()
        if msg.type != web.WSMsgType.BINARY:
            await ws.close()
            return ws

        try:
            messenger = await self.engine.checkin_ws(
                msg.data, ws, request.remote, request.headers.get('User-Agent', '•••')
            )
        except Exception as e:
            self.update_cli.display(f'Error processing WS check in: {e}', 'warning', display_module='handlers')
            await ws.close()
            return ws
        if not messenger:
            await ws.close()
            return ws

        async for msg in ws:
            try:
                await self.engine.send_messages_upstream(msg.data)
            except Exception as e:
                self.update_cli.display(f'Error processing message: {e}', 'warning', display_module='handlers')
                continue

        return ws
