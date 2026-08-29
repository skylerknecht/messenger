import asyncio
import socket

from abc import ABC, abstractmethod
from messenger.generator import alphanumeric_identifier
from messenger.message import (
    InitiateTCPClientReq,
    SendDataMessage
)

class TcpClient(ABC):
    CHUNK_SIZE = 4096

    def __init__(self, reader, writer, messenger, on_close):
        self.identifier = alphanumeric_identifier()
        self.reader = reader
        self.writer = writer
        self.messenger = messenger
        self.on_close = on_close

    def _cleanup(self, abort=False):
        if not self.on_close(self):
            return False
        if abort:
            self.writer.transport.abort()
        else:
            self.writer.close()
        return True

    @abstractmethod
    async def initiate_tcp_client(self):
        pass

    async def stream(self):
        while True:
            try:
                downstream_message = await self.reader.read(4096)
                if not downstream_message:
                    break
                self.messenger.update_cli.display(
                    f'TCP Client {self.identifier} sent {len(downstream_message)} bytes.',
                    'debug',
                    display_module='forwarders'                )
                self.messenger.update_cli.display(
                    f'TCP Client {self.identifier} sent\n{downstream_message}.',
                    'debug',
                    display_module='forwarders'                )
                await self.messenger.send_message_downstream(
                    SendDataMessage(
                        client_id=self.identifier,
                        data=downstream_message
                    )
                )
            except Exception:
                break
        if self._cleanup():
            await self.messenger.send_message_downstream(
                SendDataMessage(
                    client_id=self.identifier,
                    data=b''
                )
            )

    async def send_data(self, data):
        if len(data) == 0:
            self._cleanup()
            return
        try:
            self.writer.write(data)
            await self.writer.drain()
        except Exception:
            if self._cleanup():
                await self.messenger.send_message_downstream(
                    SendDataMessage(
                        client_id=self.identifier,
                        data=b''
                    )
                )

class LocalTcpClient(TcpClient):
    def __init__(self, destination_host, destination_port, reader, writer, messenger, on_close):
        super().__init__(reader, writer, messenger, on_close)
        self.destination_host = destination_host
        self.destination_port = destination_port

    async def initiate_tcp_client(self):
        try:
            await self.send_initiate_tcp_client_req()
        except Exception:
            self._cleanup()

    async def send_initiate_tcp_client_req(self):
        downstream_message = InitiateTCPClientReq(
            client_id=self.identifier,
            destination_host=self.destination_host,
            destination_port=int(self.destination_port)
        )
        await self.messenger.send_message_downstream(downstream_message)

    async def handle_initiate_tcp_client_rep(self, bind_addr, bind_port, atype, rep):
        if rep != 0:
            self._cleanup(abort=True)
            return
        asyncio.create_task(self.stream())

class RemoteTcpClient(TcpClient):
    def __init__(self, identifier, reader, writer, messenger, on_close):
        super().__init__(reader, writer, messenger, on_close)
        self.identifier = identifier

    async def initiate_tcp_client(self):
        asyncio.create_task(self.stream())

class SocksTcpClient(LocalTcpClient):
    def __init__(self, reader, writer, messenger, on_close):
        super().__init__('*', '*', reader, writer, messenger, on_close)

    async def initiate_tcp_client(self):
        try:
            if not await self.negotiate_authentication_method():
                return self._cleanup()
            if not await self.negotiate_transport():
                return self._cleanup()
            if not await self.negotiate_address():
                return self._cleanup()
            await self.send_initiate_tcp_client_req()
        except Exception:
            self._cleanup()

    async def handle_initiate_tcp_client_rep(self, bind_addr, bind_port, atype, rep):
        socks_connect_results = self.create_socks_reply(rep, bind_addr, bind_port, atype)
        try:
            self.writer.write(socks_connect_results)
            await self.writer.drain()
        except Exception:
            self._cleanup()
            return
        if rep != 0:
            self._cleanup()
            return
        asyncio.create_task(self.stream())

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
        version, number_of_methods = await self.reader.readexactly(2)
        if version != 5:
            self.messenger.update_cli.display(f'SOCKSv{version} is not supported, please use SOCKSv5.', 'error', display_module='forwarders')
            return False
        methods = [ord(await self.reader.readexactly(1)) for _ in range(number_of_methods)]
        if 0 not in methods:
            disconnect_reply = bytes([
                5,
                int('FF', 16)
            ])
            self.writer.write(disconnect_reply)
            await self.writer.drain()
            return False
        connect_reply = bytes([
            5,
            0
        ])
        self.writer.write(connect_reply)
        await self.writer.drain()
        return True

    async def negotiate_transport(self) -> bool:
        version, cmd, reserved_bit = await self.reader.readexactly(3)
        if version != 5:
            self.writer.write(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
            await self.writer.drain()
            return False
        if reserved_bit != 0:
            self.writer.write(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
            await self.writer.drain()
            return False
        if cmd != 1:
            self.writer.write(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')
            await self.writer.drain()
            return False
        return True

    async def negotiate_address(self) -> bool:
        self.address_type = int.from_bytes(await self.reader.readexactly(1), byteorder='big')
        if self.address_type == 1:  # IPv4
            self.destination_host = socket.inet_ntoa(await self.reader.readexactly(4))
            self.destination_port = int.from_bytes(await self.reader.readexactly(2), byteorder='big')
            return True

        elif self.address_type == 3:  # FQDN
            fqdn_length = int.from_bytes(await self.reader.readexactly(1), byteorder='big')
            fqdn = await self.reader.readexactly(fqdn_length)
            self.destination_host = fqdn.decode('utf-8')
            self.destination_port = int.from_bytes(await self.reader.readexactly(2), byteorder='big')
            return True

        elif self.address_type == 4:  # IPv6
            self.destination_host = socket.inet_ntop(socket.AF_INET6, await self.reader.readexactly(16))
            self.destination_port = int.from_bytes(await self.reader.readexactly(2), byteorder='big')
            return True

        self.writer.write(b'\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00')
        await self.writer.drain()
        return False