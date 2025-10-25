import asyncio
import errno
import socket
import re
from abc import abstractmethod

from messenger.generator import alphanumeric_identifier
from messenger.message import (
    InitiateForwarderClientRep,
)
from messenger.forwarder_clients import (
    LocalForwarderClient,
    RemoteForwarderClient,
    SocksForwarderClient
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
        self.clients = []
        self.on_close = lambda c: self.clients.remove(c) if c in self.clients else None

    @abstractmethod
    async def handle_initiate_forwarder_client_req(self, message):
        pass

    @abstractmethod
    async def handle_initiate_forwarder_client_rep(self, message):
        pass

    @staticmethod
    def is_valid_domain(domain: str) -> bool:
        DOMAIN_REGEX = re.compile(
            r'^(?=^.{1,253}$)(?!-)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}$'
        )
        return bool(DOMAIN_REGEX.match(domain))

    @staticmethod
    def is_valid_ip(ip):
        """
        Validate if the given string is a valid IPv4 or IPv6 address.

        :param ip: IP address as a string
        :return: True if valid IP address, False otherwise
        """
        try:
            socket.inet_aton(ip)  # Check for valid IPv4
            return True
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, ip)  # Check for valid IPv6
                return True
            except socket.error:
                return False

    @staticmethod
    def is_valid_port(port):
        """
        Validate if the given port is a valid TCP port.

        :param port: Port number as an integer or string
        :return: True if valid TCP port, False otherwise
        """
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

    async def handle_initiate_forwarder_client_rep(self, message):
        forwarder_client_id = message.forwarder_client_id
        for forwarder_client in self.clients:
            if forwarder_client.identifier != forwarder_client_id:
                continue
            if message.reason != 0:
                forwarder_client.writer.close()
                await forwarder_client.writer.wait_closed()
                self.clients.remove(forwarder_client)
                break
            await forwarder_client.handle_initiate_forwarder_client_rep(message.bind_address, message.bind_port, message.address_type, message.reason)
            break

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = LocalForwarderClient(self.destination_host, self.destination_port, reader, writer, self.messenger, self.on_close)
        await client.initiate_forwarder_client()
        self.clients.append(client)

    def parse_config(self, config):
        parts = config.split(':')

        if len(parts) <= 3:
            raise InvalidConfigError(f'Invalid configuration `{config}`, a {self.NAME} requires a complete configuration.')
        elif len(parts) == 4:
            listening_host, listening_port, destination_host, destination_port = parts
        else:
            raise InvalidConfigError("Invalid configuration format for LocalPortForwarder.")
        #
        # if not self.is_valid_ip(listening_host) and not self.is_valid_domain(listening_host):
        #     raise InvalidConfigError(f'The listening host `{listening_host}` does not appear to be a valid ip or domain.')
        #
        # if not self.is_valid_ip(destination_host) and not self.is_valid_domain(destination_host):
        #     raise InvalidConfigError(f'The destination host `{destination_host}` does not appear to be a valid ip or domain.')

        if not self.is_valid_port(listening_port):
            raise InvalidConfigError(f'The listening host `{listening_port}` does not appear to be a valid port.')

        if not self.is_valid_port(destination_port):
            raise InvalidConfigError(f'The destination host `{destination_port}` does not appear to be a valid port.')

        return listening_host, int(listening_port), destination_host, int(
            destination_port) if destination_port != '*' else destination_port

    async def start(self):
        self.update_cli.display(
            f'Attempting to forward ({self.listening_host}:{self.listening_port}) -> ({self.destination_host}:{self.destination_port}).',
            'information', reprompt=False)
        try:
            self.server = await asyncio.start_server(self.handle_client, self.listening_host, int(self.listening_port))
            self.update_cli.display(
                f'Messenger `{self.messenger.identifier}` now forwarding ({self.listening_host}:{self.listening_port}) -> ({self.destination_host}:{self.destination_port}).',
                'success', reprompt=False)
            return True
        except OSError as e:
            if e.errno == 98:  # Typically "Address already in use" on Linux
                self.update_cli.display(
                    f"Port {self.listening_port} is already in use on {self.listening_host}.",
                    'error',
                    reprompt=False
                )
            elif e.errno == 99:  # "Cannot assign requested address"
                self.update_cli.display(
                    f"Cannot bind to host '{self.listening_host}'—it may be invalid or unreachable.",
                    'error',
                    reprompt=False
                )
            else:
                self.update_cli.display(
                    f"Failed to bind on {self.listening_host}:{self.listening_port}: {e}",
                    'error',
                    reprompt=False
                )

        return False

    async def stop(self):
        self.server.close()

        for client in self.clients:
            try:
                transport = client.writer.transport
                if transport:
                    transport.abort()
            except Exception:
                pass

        try:
            await self.server.wait_closed()
        except Exception:
            pass

        self.update_cli.display(
            f'Messenger `{self.messenger.identifier}` has stopped forwarding ({self.listening_host}:{self.listening_port}) -> ({self.destination_host}:{self.destination_port}).',
            'success',
            reprompt=False
        )

class SocksProxy(LocalPortForwarder):

    NAME = "Socks Proxy"

    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        self.update_cli = update_cli
        listening_host, listening_port, destination_host, destination_port = self.parse_config(config)
        Forwarder.__init__(self, listening_host, listening_port, '*', '*', update_cli)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = SocksForwarderClient(reader, writer, self.messenger, self.on_close)
        await client.initiate_forwarder_client()
        self.clients.append(client)

    def parse_config(self, config):
        parts = config.split(':')

        listening_host = '127.0.0.1'
        destination_host = '*'
        destination_port = '*'

        if len(parts) == 1:
            listening_port = parts[0]

        elif len(parts) == 2:
            listening_host, listening_port = parts

        elif len(parts) == 3:
            raise InvalidConfigError(f'Invalid configuration `{config}`, cannot specify destination host without destination port.')

        elif len(parts) == 4:
            self.update_cli.display(f'Invalid configuration `{config}`, cannot set a destination host and port for a {self.NAME}.', 'warning', reprompt=False)
            listening_host, listening_port, _, _ = parts

        else:
            raise InvalidConfigError("Invalid configuration format for LocalPortForwarder.")

        # if not self.is_valid_ip(listening_host) and not self.is_valid_domain(listening_host):
        #     raise InvalidConfigError(f'The listening host `{listening_host}` does not appear to be a valid ip or domain.')

        if destination_host != '*' and not (self.is_valid_ip(destination_host) or self.is_valid_domain(destination_host)):
            raise InvalidConfigError(f'The destination host `{destination_host}` does not appear to be a valid ip or domain.')

        if not self.is_valid_port(listening_port):
            raise InvalidConfigError(f'The listening port `{listening_port}` does not appear to be a port.')

        if destination_port != '*' and not self.is_valid_port(destination_port):
            raise InvalidConfigError(f'The destination port `{destination_port}` does not appear to be a port.')

        return listening_host, int(listening_port), destination_host, int(
            destination_port) if destination_port != '*' else destination_port


class RemotePortForwarder(Forwarder):

    NAME = "Remote Port Forwarder"

    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        self.update_cli = update_cli
        destination_host, destination_port = self.parse_config(config)
        super().__init__('*', '*', destination_host, destination_port, update_cli)

    async def handle_initiate_forwarder_client_rep(self, message):
        pass

    async def handle_initiate_forwarder_client_req(self, message):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.destination_host, self.destination_port),
                timeout=5
            )

            client = RemoteForwarderClient(message.forwarder_client_id, reader, writer, self.messenger, self.on_close)
            await client.initiate_forwarder_client()
            self.clients.append(client)

            bind_info = writer.get_extra_info("sockname")
            bind_addr = bind_info[0]
            bind_port = bind_info[1]

            sock = writer.get_extra_info("socket")
            family = sock.family
            atype = 1 if family == socket.AF_INET else 4

            upstream_message = InitiateForwarderClientRep(
                forwarder_client_id=message.forwarder_client_id,
                bind_address=bind_addr,
                bind_port=bind_port,
                address_type=atype,
                reason=0
            )
        except socket.gaierror:
            reason = 4
        except socket.timeout:
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
            reason = 1
        else:
            await self.messenger.send_message_upstream(upstream_message)
            return

        upstream_message = InitiateForwarderClientRep(
            forwarder_client_id=message.forwarder_client_id,
            bind_address="0.0.0.0",
            bind_port=0,
            address_type=1,
            reason=reason
        )
        await self.messenger.send_message_upstream(upstream_message)


    def parse_config(self, config):
        parts = config.split(':')

        if len(parts) == 2:
            destination_host, destination_port = parts
        else:
            raise InvalidConfigError(f'Invalid configuration `{config}`, a {self.NAME} expects a destination host and destination port.')

        # if not self.is_valid_ip(destination_host) and not self.is_valid_domain(destination_host):
        #     raise InvalidConfigError(f'The destination host `{destination_host}` does not appear to be a valid ip or domain.')

        if not self.is_valid_port(destination_port):
            raise InvalidConfigError(f'The destination port `{destination_port}` does not appear to be a port.')

        return destination_host, int(destination_port)

    async def start(self):
        self.update_cli.display(f'Messenger `{self.messenger.identifier}` now forwarding (*:*) -> ({self.destination_host}:{self.destination_port}).', 'success', reprompt=False)


class InvalidConfigError(Exception):
    """Raised when a provided config string is invalid."""
    pass
