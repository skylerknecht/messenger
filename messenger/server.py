import sys
import ssl
import traceback

from aiohttp import web, web_protocol
from messenger.aes import decrypt, encrypt
from messenger.messengers import HTTPMessenger, WSMessenger
from messenger.message import MessageBuilder, MessageParser
from messenger.generator import alphanumeric_identifier, generate_encryption_key, generate_hash


class Server:
    def __init__(self, messengers, update_cli, address: str = '127.0.0.1', port: int = 1337, ssl: tuple = None, encryption_key: str = None):
        self.messengers = messengers
        self.update_cli = update_cli
        self.address = address
        self.port = port
        self.ssl = ssl
        self.encryption_key = encryption_key if encryption_key is not None else generate_encryption_key()
        self.update_cli.display(f'The AES encryption key is {self.update_cli.bold_text(self.encryption_key)}', 'Information', reprompt=False)
        self.encryption_key = generate_hash(self.encryption_key)
        self.app = web.Application()
        self.app.on_response_prepare.append(self.remove_server_header)
        self.app.router.add_routes([
            web.route('*', '/{tail:.*}', self.redirect_handler)
        ])

    async def http_get_handler(self, request):
        user_agent = request.headers.get('User-Agent', 'Unknown')
        ip = request.remote
        messenger = HTTPMessenger(self.encryption_key, self.update_cli)
        messenger.user_agent = user_agent
        messenger.ip = ip
        self.messengers.append(messenger)
        self.update_cli.display(f'{messenger.transport} Messenger {messenger.identifier} has successfully connected.', 'success')
        return web.Response(status=200, text=messenger.identifier)

    async def http_post_handler(self, request):
        user_agent = request.headers.get('User-Agent', 'Unknown')
        ip = request.remote
        # Read the binary data from the request
        try:
            data = decrypt(self.encryption_key, await request.read())
        except:
            self.update_cli.display(f'HTTP Messenger failed to decrypt message.', 'error')
            return web.Response(status=500)
        # Parse the binary blob into individual messages
        downstream_messages = MessageParser.parse_messages(data)
        upstream_messages = b''
        check_in_message = downstream_messages[0]
        messenger_id = check_in_message.get('Messenger ID')
        if not messenger_id:
            self.update_cli.display(f'HTTP Messenger Check-In missing a Messenger ID!', 'error')
            return web.Response(status=500)
        for messenger in self.messengers:
            if messenger.identifier == messenger_id:
                upstream_messages += await messenger.get_upstream_messages()
                for downstream_message in downstream_messages[1:]:
                    await messenger.handle_message(downstream_message)
                break
        else:
            messenger = HTTPMessenger(self.update_cli)
            messenger.identifier = messenger_id
            messenger.user_agent = user_agent
            messenger.ip = ip
            self.messengers.append(messenger)
            self.update_cli.display(f'{messenger.transport} Messenger {messenger.identifier} has successfully connected.', 'success')
            return web.Response(status=200)
        return web.Response(status=200, body=encrypt(self.encryption_key, upstream_messages))

    @staticmethod
    async def remove_server_header(request, response):
        if 'Server' in response.headers:
            del response.headers['Server']

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        try:
            if self.ssl:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(self.ssl[0], self.ssl[1])
                site = web.TCPSite(runner, self.address, self.port, ssl_context=ssl_context)
                await site.start()
            else:
                site = web.TCPSite(runner, self.address, self.port)
                await site.start()
            self.update_cli.display(f"Waiting for messengers on http{'s' if self.ssl else ''}+ws{'s' if self.ssl else ''}://{self.address}:{self.port}/", 'Information', reprompt=False)
        except OSError:
            self.update_cli.display(f'An error prevented the server from starting:\n{traceback.format_exc()}', 'error', reprompt=False)
            sys.exit(1)

    async def websocket_handler(self, request):
        user_agent = request.headers.get('User-Agent', 'Unknown')
        ip = request.remote
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        messenger = WSMessenger(websocket, self.encryption_key, self.update_cli)
        messenger.user_agent = user_agent
        messenger.ip = ip
        self.messengers.append(messenger)
        self.update_cli.display(f'{messenger.transport} Messenger {messenger.identifier} has successfully connected.', 'success')
        async for downstream_message in websocket:
            try:
                decrypted_message = decrypt(self.encryption_key, downstream_message.data)
            except:
                self.update_cli.display(f'{messenger.transport} Messenger {messenger.identifier} failed to decrypt message.', 'error')
                break
            messages = MessageParser.parse_messages(decrypted_message)
            for message in messages:
                await messenger.handle_message(message)

        self.update_cli.display(f'{messenger.transport} Messenger {messenger.identifier} has disconnected.', 'warning')
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
