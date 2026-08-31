import asyncio
import errno
import socket
from abc import abstractmethod

from messenger.generator import alphanumeric_identifier
from messenger.message import (
    InitiateTCPClientRep,
    InitiateBINDReq,
    SendDataMessage,
)
from messenger.tcp_clients import (
    LocalTcpClient,
    RemoteTcpClient,
    SocksTcpClient
)

class Forwarder:

    NAME = "Unnamed Forwarder"

    def __init__(self, listening_host, listening_port, destination_host, destination_port, update_cli):
        self.listening_host = listening_host
        self.listening_port = listening_port
        self.destination_host = destination_host
        self.destination_port = destination_port
        self.update_cli = update_cli
        self.identifier = alphanumeric_identifier()
        self._nickname = None
        self.stopped = False
        self.clients = []
        def _remove_client(c):
            if c in self.clients:
                self.clients.remove(c)
                return True
            return False
        self.on_close = _remove_client

    @property
    def nickname(self):
        return self._nickname or self.identifier

    @nickname.setter
    def nickname(self, value):
        self._nickname = value

    @abstractmethod
    async def handle_initiate_tcp_client_req(self, message):
        pass

    @abstractmethod
    async def handle_initiate_tcp_client_rep(self, message):
        pass

    @staticmethod
    def _split_config(config):
        parts = []
        i = 0
        while i < len(config):
            if config[i] == '[':
                close = config.find(']', i)
                if close == -1:
                    raise InvalidConfigError(f'Invalid configuration `{config}`, unmatched `[`.')
                if close + 1 < len(config) and config[close + 1] != ':':
                    raise InvalidConfigError(f'Invalid configuration `{config}`, `]` must be followed by `:` or end of string.')
                parts.append(config[i + 1:close])
                i = close + 2
            else:
                colon = config.find(':', i)
                if colon == -1:
                    parts.append(config[i:])
                    break
                parts.append(config[i:colon])
                i = colon + 1
        return parts

    @staticmethod
    def is_valid_port(port):
        try:
            port = int(port)
            return 1 <= port <= 65535
        except ValueError:
            return False


class LocalPortForwarder(Forwarder):

    NAME = "Local Port Forwarder"

    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        self.update_cli = update_cli
        self.server = None
        listening_host, listening_port, destination_host, destination_port = self.parse_config(config)
        super().__init__(listening_host, listening_port, destination_host, destination_port, update_cli)

    async def handle_initiate_tcp_client_rep(self, message):
        client_id = message.client_id
        for tcp_client in self.clients:
            if tcp_client.identifier != client_id:
                continue
            await tcp_client.handle_initiate_tcp_client_rep(message.bind_address, message.bind_port, message.address_type, message.reason)
            break

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.stopped or self.messenger.checked_out:
            writer.close()
            return
        client = LocalTcpClient(self.destination_host, self.destination_port, reader, writer, self.messenger, self.on_close)
        self.clients.append(client)
        await client.initiate_tcp_client()

    def parse_config(self, config):
        parts = self._split_config(config)

        if len(parts) != 4:
            raise InvalidConfigError(f'Invalid configuration `{config}`, a {self.NAME} requires listening_host:listening_port:destination_host:destination_port.')

        listening_host, listening_port, destination_host, destination_port = parts

        if not self.is_valid_port(listening_port):
            raise InvalidConfigError(f'The listening port `{listening_port}` does not appear to be a valid port.')

        if not self.is_valid_port(destination_port):
            raise InvalidConfigError(f'The destination port `{destination_port}` does not appear to be a valid port.')

        return listening_host, int(listening_port), destination_host, int(destination_port)

    def _endpoint_str(self):
        listen = f'{self.listening_host}:{self.listening_port}'
        if self.destination_host == '*':
            return listen
        return f'{listen} -> {self.destination_host}:{self.destination_port}'

    async def start(self):
        self.update_cli.display(
            f'Messenger `{self.messenger.nickname}` is attempting to start {self.NAME} ({self._endpoint_str()}).',
            'information', reprompt=False, display_module='forwarders')
        try:
            self.server = await asyncio.start_server(self.handle_client, self.listening_host, int(self.listening_port))
            self.update_cli.display(
                f'Messenger `{self.messenger.nickname}` started {self.NAME} ({self._endpoint_str()}).',
                'success', reprompt=False, display_module='forwarders')
            return True
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                reason = 'address already in use'
            elif e.errno == errno.EADDRNOTAVAIL:
                reason = 'address not available'
            elif e.errno == errno.EACCES:
                reason = 'permission denied'
            else:
                reason = str(e)
            self.update_cli.display(
                f'Messenger `{self.messenger.nickname}` failed to bind ({self.listening_host}:{self.listening_port}): {reason}.',
                'error',
                reprompt=False, display_module='forwarders'
            )

        return False

    async def stop(self):
        if not self.server:
            return
        self.stopped = True
        self.server.close()

        for client in list(self.clients):
            client_id = client.identifier
            if client._cleanup(abort=True):
                await self.messenger.send_message_downstream(
                    SendDataMessage(client_id=client_id, data=b'')
                )

        self.update_cli.display(
            f'Messenger `{self.messenger.nickname}` stopped {self.NAME} ({self._endpoint_str()}).',
            'success',
            reprompt=False, display_module='forwarders'
        )

class SocksProxy(LocalPortForwarder):

    NAME = "SOCKS Server"

    def __init__(self, messenger, config, update_cli):
        super().__init__(messenger, config, update_cli)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.stopped or self.messenger.checked_out:
            writer.close()
            return
        client = SocksTcpClient(reader, writer, self.messenger, self.on_close)
        self.clients.append(client)
        await client.initiate_tcp_client()

    def parse_config(self, config):
        parts = self._split_config(config)

        listening_host = '127.0.0.1'

        if len(parts) == 1:
            listening_port = parts[0]
        elif len(parts) == 2:
            listening_host, listening_port = parts
        else:
            raise InvalidConfigError(f'Invalid configuration `{config}`, a {self.NAME} requires listening_port or listening_host:listening_port.')

        if not self.is_valid_port(listening_port):
            raise InvalidConfigError(f'The listening port `{listening_port}` does not appear to be a valid port.')

        return listening_host, int(listening_port), '*', '*'


class RemotePortForwarder(Forwarder):

    NAME = "Remote Port Forwarder"

    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        self.update_cli = update_cli
        listening_host, listening_port, destination_host, destination_port = self.parse_config(config)
        super().__init__(listening_host, listening_port, destination_host, destination_port, update_cli)
        self.forwarding = False

    @classmethod
    def orphan(cls, messenger, bind_id, listening_host, listening_port, update_cli):
        self = cls.__new__(cls)
        self.messenger = messenger
        self.update_cli = update_cli
        Forwarder.__init__(self, listening_host, int(listening_port), '', 0, update_cli)
        self.identifier = bind_id
        self.forwarding = True
        return self

    @property
    def is_orphan(self):
        # No destination configured yet -> cannot route.
        return not self.destination_host

    def close_all_clients(self):
        # RST every forwarded connection this RPF owns. Synchronous (abort()
        # doesn't await) so it stays atomic between yield points.
        for client in list(self.clients):
            try:
                transport = client.writer.transport
                if transport:
                    transport.abort()
            except Exception:
                pass

    async def handle_initiate_tcp_client_rep(self, message):
        pass

    async def handle_initiate_tcp_client_req(self, message):
        if self.stopped or self.messenger.checked_out:
            return
        if self.is_orphan:
            # No destination set -- deny; the operator must configure it first.
            await self.messenger.send_message_downstream(
                InitiateTCPClientRep(
                    client_id=message.client_id, bind_address="0.0.0.0",
                    bind_port=0, address_type=1, reason=2
                )
            )
            return
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.destination_host, self.destination_port),
                timeout=5
            )

            if self.stopped or self.messenger.checked_out:
                writer.close()
                return

            client = RemoteTcpClient(message.client_id, reader, writer, self.messenger, self.on_close)
            self.clients.append(client)

            downstream_message = InitiateTCPClientRep(
                client_id=message.client_id,
                bind_address="0.0.0.0",
                bind_port=0,
                address_type=1,
                reason=0
            )
        except socket.gaierror:
            reason = 4
        except (socket.timeout, asyncio.TimeoutError):
            reason = 6
        except ConnectionRefusedError:
            reason = 5
        except OSError as e:
            reason = {
                errno.ENETUNREACH: 3,
                errno.EHOSTUNREACH: 4,
                errno.ECONNREFUSED: 5,
                errno.ENOPROTOOPT: 7,
                errno.EAFNOSUPPORT: 8
            }.get(e.errno, 1)
        except Exception as e:
            self.update_cli.log_unexpected_error(e)
            reason = 1
        else:
            await self.messenger.send_message_downstream(downstream_message)
            await client.initiate_tcp_client()
            return

        downstream_message = InitiateTCPClientRep(
            client_id=message.client_id,
            bind_address="0.0.0.0",
            bind_port=0,
            address_type=1,
            reason=reason
        )
        await self.messenger.send_message_downstream(downstream_message)

    def parse_config(self, config):
        parts = self._split_config(config)

        if len(parts) != 4:
            raise InvalidConfigError(f'Invalid configuration `{config}`, a {self.NAME} requires listening_host:listening_port:destination_host:destination_port.')

        listening_host, listening_port, destination_host, destination_port = parts

        if not self.is_valid_port(listening_port):
            raise InvalidConfigError(f'The listening port `{listening_port}` does not appear to be a valid port.')

        if not self.is_valid_port(destination_port):
            raise InvalidConfigError(f'The destination port `{destination_port}` does not appear to be a valid port.')

        return listening_host, int(listening_port), destination_host, int(destination_port)

    async def start(self):
        bind_req = InitiateBINDReq(
            bind_id=self.identifier,
            listening_host=self.listening_host,
            listening_port=self.listening_port,
            destination_host=self.destination_host,
            destination_port=self.destination_port
        )
        await self.messenger.send_message_downstream(bind_req)
        self.update_cli.display(
            f'Queued bind request for Messenger `{self.messenger.nickname}` for '
            f'({self.listening_host}:{self.listening_port}) -> '
            f'({self.destination_host}:{self.destination_port}).',
            'information', display_module='forwarders'
        )

    async def stop(self):
        self.stopped = True
        bind_req = InitiateBINDReq(
            bind_id=self.identifier,
            listening_host='',
            listening_port=0,
            destination_host='',
            destination_port=0
        )
        await self.messenger.send_message_downstream(bind_req)
        self.update_cli.display(
            f'Sent stop to Messenger `{self.messenger.nickname}` for Remote Port Forwarder '
            f'`{self.identifier}` ({self.listening_host}:{self.listening_port}).',
            'information', display_module='forwarders'
        )
        self.close_all_clients()


class InvalidConfigError(Exception):
    """Raised when a provided config string is invalid."""
    pass
