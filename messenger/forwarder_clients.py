import asyncio
import socket

from abc import ABC, abstractmethod
from messenger.generator import alphanumeric_identifier
from messenger.message import (
    InitiateForwarderClientReq,
    InitiateForwarderClientRep,
    SendDataMessage
)

class ForwarderClient(ABC):
    CHUNK_SIZE = 4096

    def __init__(self, reader, writer, messenger, on_close):
        self.identifier = alphanumeric_identifier()
        self.reader = reader
        self.writer = writer
        self.messenger = messenger
        self.on_close = on_close

    @abstractmethod
    async def initiate_forwarder_client(self):
        pass

    async def receive_data(self):
        while True:
            try:
                upstream_message = await self.reader.read(4096)
                if not upstream_message:
                    break
                self.messenger.sent_bytes += len(upstream_message)
                self.messenger.update_cli.display(
                    f'Forwarder Client {self.identifier} sent {len(upstream_message)} bytes.',
                    'debug',
                    debug_level=3
                )
                self.messenger.update_cli.display(
                    f'Forwarder Client {self.identifier} sent\n{upstream_message}.',
                    'debug',
                    debug_level=6
                )
                await self.messenger.send_message_upstream(
                    SendDataMessage(
                        forwarder_client_id=self.identifier,
                        data=upstream_message
                    )
                )
            except (EOFError, ConnectionResetError):
                break
        self.on_close(self)
        await self.messenger.send_message_upstream(
            SendDataMessage(
                forwarder_client_id=self.identifier,
                data=b''  # empty to signal close
            )
        )

    async def send_data(self, data):
        if len(data) == 0:
            self.writer.write_eof()
            return
        self.messenger.received_bytes += len(data)
        self.writer.write(data)

class LocalForwarderClient(ForwarderClient):
    def __init__(self, destination_host, destination_port, reader, writer, messenger, on_close):
        super().__init__(reader, writer, messenger, on_close)
        self.destination_host = destination_host
        self.destination_port = destination_port

    async def initiate_forwarder_client(self):
        await self.send_initiate_forwarder_client_req()

    async def send_initiate_forwarder_client_req(self):
        upstream_message = InitiateForwarderClientReq(
            forwarder_client_id=self.identifier,
            ip_address=self.destination_host,
            port=int(self.destination_port)
        )
        self.messenger.sent_bytes += 20
        await self.messenger.send_message_upstream(upstream_message)

    async def handle_initiate_forwarder_client_rep(self, bind_addr, bind_port, atype, rep):
        if rep != 0:
            return
        asyncio.create_task(self.receive_data())

class RemoteForwarderClient(ForwarderClient):
    def __init__(self, identifier, reader, writer, messenger, on_close):
        super().__init__(reader, writer, messenger, on_close)
        self.identifier = identifier

    async def initiate_forwarder_client(self):
        asyncio.create_task(self.receive_data())

class SocksForwarderClient(LocalForwarderClient):
    def __init__(self, reader, writer, messenger, cleanup):
        super().__init__('*', '*', reader, writer, messenger, cleanup)

    async def initiate_forwarder_client(self):
        if not await self.negotiate_authentication_method():
            return
        if not await self.negotiate_transport():
            return
        if not await self.negotiate_address():
            return

        await self.send_initiate_forwarder_client_req()

    async def handle_initiate_forwarder_client_rep(self, bind_addr, bind_port, atype, rep):
        if rep != 0:
            self.on_close(self)
            return
        socks_connect_results = self.create_socks_reply(rep, bind_addr, bind_port, atype)
        self.messenger.received_bytes += len(socks_connect_results)
        self.writer.write(socks_connect_results)
        asyncio.create_task(self.receive_data())

    @staticmethod
    def create_socks_reply(rep, bind_addr, bind_port, atype):
        if atype == 1: # IPv4
            addr_bytes = (
                socket.inet_aton(bind_addr) if bind_addr else b'\x00\x00\x00\x00'
            )
        elif atype == 3: # FQDN
            addr_bytes = (
                len(bind_addr).to_bytes(1, 'big') + bind_addr.encode()
                if bind_addr else b'\x00'
            )
        elif atype == 4: # IPv6
            addr_bytes = (
                socket.inet_pton(socket.AF_INET6, bind_addr)
                if bind_addr else b'\x00' * 16
            )
        else:
            raise ValueError(f"Could not create SOCKS5 reply, unsupported address type: {atype}")

        return b''.join([
            b'\x05',
            int(rep).to_bytes(1, 'big'),
            b'\x00',  # Reserved
            atype.to_bytes(1, 'big'),
            addr_bytes,
            bind_port.to_bytes(2, 'big') if bind_port else b'\x00\x00'
        ])

    async def negotiate_authentication_method(self) -> bool:
        version, number_of_methods = await self.reader.read(2)
        if version != 5:
            self.messenger.update_cli.display(f'SOCKSv{version} is not supported, please use SOCKSv5.', 'error')
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
        version, cmd, reserved_bit = await self.reader.read(3)
        return cmd == 1

    async def negotiate_address(self) -> bool:
        self.address_type = int.from_bytes(await self.reader.read(1), byteorder='big')
        if self.address_type == 1:  # IPv4
            self.destination_host = socket.inet_ntoa(await self.reader.read(4))
            self.destination_port = int.from_bytes(await self.reader.read(2), byteorder='big')
            return True

        elif self.address_type == 3:  # FQDN
            fqdn_length = int.from_bytes(await self.reader.read(1), byteorder='big')
            fqdn = await self.reader.read(fqdn_length)
            self.destination_host = fqdn.decode('utf-8')
            self.destination_port = int.from_bytes(await self.reader.read(2), byteorder='big')
            return True

        elif self.address_type == 4:  # IPv6
            self.destination_host = socket.inet_ntop(socket.AF_INET6, await self.reader.read(16))
            self.destination_port = int.from_bytes(await self.reader.read(2), byteorder='big')
            return True

        return False