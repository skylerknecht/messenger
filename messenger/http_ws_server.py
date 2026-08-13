import ssl
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
        app = web.Application()
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
            self.update_cli.display(f"Waiting for messengers on http{'s' if self.ssl else ''}+ws{'s' if self.ssl else ''}://{self.ip}:{self.port}/", 'information', reprompt=False, display_module='handlers')
        except OSError:
            self.update_cli.display(f'An error prevented the server from starting:\n{traceback.format_exc()}', 'error', reprompt=False, display_module='handlers')

    @staticmethod
    async def remove_server_header(_, response):
        if 'Server' in response.headers:
            del response.headers['Server']

    async def redirect_handler(self, request):
        ip = request.remote
        upgrade = request.headers.get('Upgrade', '').lower()
        is_websocket = upgrade == 'websocket'

        self.update_cli.display(
            f'The handler received a {request.method} from {ip}.',
            'debug', display_module='handlers', debug_level=1,
        )

        if is_websocket:
            return await self.websocket_handler(request)
        if request.method == 'POST':
            return await self.http_post_handler(request)
        return web.Response(status=404, text='Not Found')

    async def http_post_handler(self, request):
        ip = request.remote
        user_agent = request.headers.get('User-Agent', '•••')

        upstream_message_data = b''
        data = await request.read()
        self.update_cli.display(
            f'The handler received {len(data)} bytes from {ip}\n{data}.',
            'debug', display_module='handlers', debug_level=2,
        )
        messages = self.messenger_engine.deserialize_messages(data) if data else []
        messenger_id = self.messenger_engine.get_messenger_id(messages[0]) if messages else None
        if messenger_id is None:
            self.update_cli.display('Unable to identify Messenger, the CheckIn message was not present', 'warning', display_module='handlers')
            return web.Response(status=200, body=b'')
        try:
            messenger = self.messenger_engine.get_messenger(messenger_id)
            if messenger:
                await self.messenger_engine.send_messages(messenger_id, messages[1:])
                messenger.check_in()
                if messenger.check_in_delta > 60:
                    self.update_cli.display(
                        f'{messenger.transport_type} Messenger `{messenger.nickname}` has reconnected.',
                        'success', display_module='handlers'
                    )
                upstream_message_data += await messenger.get_upstream_messages()
            else:
                http_messenger = HTTPMessenger(
                    ip,
                    user_agent,
                    self.update_cli,
                    self.messenger_engine.serialize_messages
                )
                if messenger_id:
                    http_messenger.identifier = messenger_id

                check_in_message = self.messenger_engine.add_messenger(http_messenger)

                if not messenger_id:
                    upstream_message_data += check_in_message
        except Exception as e:
            self.update_cli.display(f'Unknown error while processing check in: {e}', 'warning', display_module='handlers')
            return web.Response(status=200, body=b'')

        return web.Response(status=200, body=upstream_message_data)

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        ip = request.remote
        user_agent = request.headers.get('User-Agent', '•••')
        msg = await ws.receive()
        if msg.type != web.WSMsgType.BINARY:
            await ws.close()
            return ws
        self.update_cli.display(
            f'The handler received {len(msg.data)} bytes from {ip}\n{msg.data}.',
            'debug', display_module='handlers', debug_level=2,
        )
        messages = self.messenger_engine.deserialize_messages(msg.data) if msg.data else []
        messenger_id = self.messenger_engine.get_messenger_id(messages[0]) if messages else None
        if messenger_id is None:
            self.update_cli.display('Unable to identify Messenger, the CheckIn message was not present', 'warning', display_module='handlers')
            await ws.close()
            return ws
        messenger = self.messenger_engine.get_messenger(messenger_id)
        if messenger:
            if not isinstance(messenger, WebSocketMessenger):
                self.update_cli.display(
                    f'Messenger `{messenger_id}` is not a WebSocket Messenger, closing connection.',
                    'warning', display_module='handlers'
                )
                await ws.close()
                return ws
            messenger.set_websocket(ws)
            self.update_cli.display(
                f'{messenger.transport_type} Messenger `{messenger.nickname}` has reconnected.',
                'success', display_module='handlers'
            )
            while not messenger.upstream_messages.empty():
                message = await messenger.upstream_messages.get()
                await messenger.send_message_upstream(message)
        else:
            ws_messenger = WebSocketMessenger(
                ws,
                ip,
                user_agent,
                self.update_cli,
                self.messenger_engine.serialize_messages
            )

            if messenger_id:
                ws_messenger.identifier = messenger_id

            check_in_msg = self.messenger_engine.add_messenger(ws_messenger)

            if not messenger_id:
                await ws.send_bytes(check_in_msg)
            messenger = ws_messenger

        messenger.check_in()

        async for msg in ws:
            try:
                self.update_cli.display(
                    f'The handler received {len(msg.data) if msg.data else 0} bytes from {ip}\n{msg.data}.',
                    'debug', display_module='handlers', debug_level=2,
                )
                messages = self.messenger_engine.deserialize_messages(msg.data) if msg.data else []
                if not messages:
                    continue
                messenger_id = self.messenger_engine.get_messenger_id(messages[0])
                if messenger_id is None:
                    continue
                await self.messenger_engine.send_messages(
                    messenger_id,
                    messages[1:]
                )
            except Exception as e:
                self.update_cli.display(f'Unknown error while processing check in: {e}', 'warning', display_module='handlers')
                continue

        messenger.check_in()
        return ws