import asyncio
import socket
import json
import uuid

from json import JSONDecodeError
from messenger import convert


class Client:
    """
    Client maintains a setup function that will process incoming connections and
    respond to the negotiation process based on the SOCKS5 protocol specification. If
    successful, setup will execute stream where all incoming data will be appended to
    the upstream_data queue.

    Client also maintains a downstream_data queue where any data appended will be sent
    to the client.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, transport, buffer_size: int):
        self.reader = reader
        self.writer = writer
        self.transport = transport
        self.buffer_size = buffer_size
        self.identifier = str(uuid.uuid4().hex)
        self.upstream = asyncio.Queue()
        self.address_type = None
        self.remote_address = None
        self.remote_port = None

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

    async def setup(self):
        if not await self.negotiate_authentication_method():
            return
        if not await self.negotiate_transport():
            return
        if not await self.negotiate_address():
            return

        socks_connect_msg = json.dumps({
            'identifier': self.identifier,
            'atype': self.address_type,
            'address': self.remote_address,
            'port': self.remote_port
        })

        if self.transport == 'http':
            await self.upstream.put(socks_connect_msg)
        else:
            await self.transport.send_str(socks_connect_msg)
        await self.stream()

    async def stream(self):
         try:
            while True:
                data = await self.reader.read(self.buffer_size)
                if not data:  # Client disconnected
                    break
                if self.transport == 'http':
                    await self.upstream.put(self.generate_upstream_message(data))
                else:
                    await self.transport.send_str(self.generate_upstream_message(data))
         except (EOFError, ConnectionResetError):
             #ToDo add debug statement
            #print(f"Client {self.identifier} disconnected unexpectedly")
            pass

    def generate_upstream_message(self, msg: bytes):
        return json.dumps({
            'identifier': self.identifier,
            'msg': convert.bytes_to_base64(msg)
        })


class SocksServer:

    def __init__(self, peername: tuple, transport='http', buffer_size=4096):
        self.host, self.port = peername
        self.transport = transport
        self.buffer_size = buffer_size
        self.clients = []
        self.socks_server = None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = Client(reader, writer, self.transport, self.buffer_size)
        self.clients.append(client)
        await client.setup()

    async def start(self):
        self.socks_server = await asyncio.start_server(self.handle_client, self.host, self.port)

    async def stop(self):
        if self.socks_server:
            self.socks_server.close()  # Stop accepting new connections
            await self.socks_server.wait_closed()  # Wait until the server is closed
            print('Socks Server Stopped on {}'.format(self.port))

        # Close all client connections
        for client in self.clients:
            if not client.writer.transport.is_closing():
                client.writer.close()
                await client.writer.wait_closed()  # Ensure the writer is fully closed

    def send_downstream(self, identifier, msg):
        msg = convert.base64_to_bytes(msg)
        for client in self.clients:
            if client.identifier == identifier:
                if not client.writer.transport.is_closing():
                    client.writer.write(msg)
