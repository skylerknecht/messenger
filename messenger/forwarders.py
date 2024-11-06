import asyncio
import socket
import uuid
import json

from messenger.convert import bytes_to_base64, base64_to_bytes
from messenger.message import MessageBuilder


class ForwarderClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, messenger):
        self.identifier = str(uuid.uuid4())
        self.reader = reader
        self.writer = writer
        self.messenger = messenger
        self.connected = False

    async def start(self):
        self.connected = True
        await self.stream()

    async def stream(self):
        while True:
            if not self.connected:
                await asyncio.sleep(1)
                continue
            try:
                upstream_message = await self.reader.read(4096)
                if not upstream_message:
                    break
                await self.messenger.send_upstream_message(MessageBuilder.send_data(self.identifier, upstream_message))
            except (EOFError, ConnectionResetError):
                break
        await self.messenger.send_upstream_message(MessageBuilder.send_data(self.identifier, b''))

    def write(self, base64_encoded_data):
        base64_decoded_data = base64_to_bytes(base64_encoded_data)
        self.writer.write(base64_decoded_data)


class LocalForwarderClient(ForwarderClient):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, remote_host, remote_port, messenger):
        self.remote_host = remote_host
        self.remote_port = remote_port
        super().__init__(reader, writer, messenger)

    async def start(self):
        upstream_message = MessageBuilder.initiate_forwarder_client_req(self.identifier, self.remote_host, int(self.remote_port))
        await self.messenger.send_upstream_message(upstream_message)
        await self.stream()

    def connect(self, bind_addr, bind_port, atype, rep):
        self.connected = True


class SocksForwarderClient(ForwarderClient):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, messenger):
        super().__init__(reader, writer, messenger)

    async def negotiate_authentication_method(self) -> bool:
        """
        The SOCKS5 protocol supports multiple authenticate methods. Depending on the
        methods sent from the client, the server can select and response with the following
        bytes.

        NO_AUTHENTICATION_REQUIRED = 0
        GSSAPI = 1
        USERNAME/PASSWORD = 2
        IANA_ASSIGNED = 3
        RESERVED_FOR_PRIVATE_METHODS = 80
        NO_ACCEPTABLE_AUTHENTICATION_METHOD = FF

        This SOCK5 implementation does not support authentication. Therefore, if zero is not
        provided then reply with FF or NO_ACCEPTABLE_AUTHENTICATION_METHOD and return False.
        Otherwise, send 0 or NO_AUTHENTICATION_REQUIRED and return True.

        :return: bool
        """
        version, number_of_methods = await self.reader.read(2)
        if version != 5:
            print(f'SOCKS{str(version)} is not supported')
            return False
        methods = [ord(await self.reader.read(1)) for _ in range(number_of_methods)]
        if 0 not in methods:
            disconnect_reply = bytes([
                5,
                int('FF', 16)
            ])
            self.writer.write(disconnect_reply)
            return False
        connect_reply = bytes([
            5,
            0
        ])
        self.writer.write(connect_reply)
        return True

    async def negotiate_transport(self) -> bool:
        """
        The SOCKS5 protocol supports multiple transport methods. The following maps CMD bits sent
        that will be sent from the client to transport methods.

        CONNECT = 1
        BIND = 2
        UDP ASSOCIATE = 3

        This SOCKS5 implementation does not support BIND and UDP ASSOCIATE. Therefore, if one is
        not provided then return False.

        :return: bool
        """
        version, cmd, reserved_bit = await self.reader.read(3)
        return cmd == 1

    import socket

    async def negotiate_address(self) -> bool:
        """
        The SOCKS5 protocol supports multiple address methods. The following maps address_type bits
        that will be sent from the client to address types.

        IPV4 = 1
        FQDN = 3
        IPv6 = 4

        This SOCKS5 implementation supports all address types and will parse the address type
        according to the address_type bit sent. If an invalid address_type bit is sent, return False.

        :return: bool
        """
        self.address_type = int.from_bytes(await self.reader.read(1), byteorder='big')
        if self.address_type == 1:  # IPv4
            self.remote_address = socket.inet_ntoa(await self.reader.read(4))
            self.remote_port = int.from_bytes(await self.reader.read(2), byteorder='big')
            return True

        elif self.address_type == 3:  # FQDN
            fqdn_length = int.from_bytes(await self.reader.read(1), byteorder='big')
            fqdn = await self.reader.read(fqdn_length)
            self.remote_address = fqdn.decode('utf-8')  # Assuming UTF-8 encoding
            self.remote_port = int.from_bytes(await self.reader.read(2), byteorder='big')
            return True

        elif self.address_type == 4:  # IPv6
            self.remote_address = socket.inet_ntop(socket.AF_INET6, await self.reader.read(16))
            self.remote_port = int.from_bytes(await self.reader.read(2), byteorder='big')
            return True

        return False

    async def start(self):
        if not await self.negotiate_authentication_method():
            return
        if not await self.negotiate_transport():
            return
        if not await self.negotiate_address():
            return

        upstream_message = MessageBuilder.initiate_forwarder_client_req(self.identifier, self.remote_address, self.remote_port)

        await self.messenger.send_upstream_message(upstream_message)

        await self.stream()

    @staticmethod
    def socks_results(rep, bind_addr, bind_port):
        return b''.join([
            b'\x05',
            int(rep).to_bytes(1, 'big'),
            int(0).to_bytes(1, 'big'),
            int(1).to_bytes(1, 'big'),
            socket.inet_aton(bind_addr) if bind_addr else int(0).to_bytes(1, 'big'),
            bind_port.to_bytes(2, 'big') if bind_port else int(0).to_bytes(1, 'big')
        ])

    def connect(self, bind_addr, bind_port, atype, rep):
        self.connected = True
        socks_connect_results = self.socks_results(rep, bind_addr, bind_port)
        self.writer.write(socks_connect_results)


class Forwarder:
    def __init__(self, local_host, local_port, remote_host, remote_port, update_cli):
        self.local_host = local_host
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.update_cli = update_cli
        self.clients = []
        self.name = "Unnamed Forwarder"


class LocalForwarder(Forwarder):
    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        local_host, local_port, remote_host, remote_port = self.parse_config(config)
        super().__init__(local_host, local_port, remote_host, remote_port, update_cli)
        self.socks = True if self.remote_port == '*' and self.remote_host == '*' else False
        self.name = "Socks Proxy" if self.socks else "Local Forwarder"
        self.server = None  # Event to signal stop

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.socks:
            client = SocksForwarderClient(reader, writer, self.messenger)
        else:
            client = LocalForwarderClient(reader, writer, self.remote_host, self.remote_port, self.messenger)
        self.clients.append(client)
        await client.start()
        self.clients.remove(client)

    def parse_config(self, config):
        parts = config.split(':')
        if len(parts) == 1:
            parts = ('127.0.0.1', parts[0], '*', '*')
        elif len(parts) == 2:
            parts = (parts[0], parts[1], '*', '*')
        return parts

    async def start(self):
        try:
            self.server = await asyncio.start_server(self.handle_client, self.local_host, int(self.local_port))
            self.update_cli.display(f'{self.name} {id(self)} is listening on {self.local_host}:{self.local_port}', 'information', reprompt=False)
            return True
        except OSError:
            self.update_cli.display(f'{self.local_host}:{self.local_port} is already in use.', 'warning', reprompt=False)
            return False

    async def stop(self):
        # Sets the stop_event to trigger shutdown
        self.server.close()  # Stop accepting new connections
        await self.server.wait_closed()  # Wait until the server is closed
        self.update_cli.display(f'{self.name} {id(self)} has stopped listening on {self.local_host}:{self.local_port}.', 'information', reprompt=False)


class RemoteForwarder(Forwarder):
    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        local_host, local_port = self.parse_config(config)
        super().__init__(local_host, local_port, '*', '*', update_cli)
        self.name = "Remote Forwarder"

    async def create_client(self, client_identifier):
        try:
            reader, writer = await asyncio.open_connection(self.local_host, self.local_port)
            bind_addr, bind_port = writer.get_extra_info('sockname')
            upstream_message = MessageBuilder.initiate_forwarder_client_rep(client_identifier, bind_addr, bind_port, 0, 0)
            await self.messenger.send_upstream_message(upstream_message)
        except:
            upstream_message = MessageBuilder.initiate_forwarder_client_rep(client_identifier, '', 0, 0, 1)
            await self.messenger.send_upstream_message(upstream_message)
            return
        client = ForwarderClient(reader, writer, self.messenger)
        client.identifier = client_identifier
        self.clients.append(client)
        await client.start()

    @staticmethod
    def parse_config(config):
        parts = config.split(':')
        return parts

    async def start(self):
        self.update_cli.display(f'{self.name} {id(self)} forwarding traffic to {self.local_host}:{self.local_port}', 'information', reprompt=False)

