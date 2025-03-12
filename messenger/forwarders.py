import asyncio
import socket
import re

from messenger.convert import base64_to_bytes
from messenger.message import MessageBuilder
from messenger.generator import alphanumeric_identifier


class ForwarderClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, messenger):
        self.identifier = alphanumeric_identifier()
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


class LocalPortForwarderClient(ForwarderClient):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, destination_host, destination_port, messenger):
        self.destination_host = destination_host
        self.destination_port = destination_port
        super().__init__(reader, writer, messenger)

    async def start(self):
        upstream_message = MessageBuilder.initiate_forwarder_client_req(self.identifier, self.destination_host, int(self.destination_port))
        await self.messenger.send_upstream_message(upstream_message)
        await self.stream()

    def connect(self, bind_addr, bind_port, atype, rep):
        self.connected = True


class SocksForwarderClient(ForwarderClient):

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, messenger):
        super().__init__(reader, writer, messenger)

    async def negotiate_authentication_method(self) -> bool:
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
        version, cmd, reserved_bit = await self.reader.read(3)
        return cmd == 1

    async def negotiate_address(self) -> bool:
        self.address_type = int.from_bytes(await self.reader.read(1), byteorder='big')
        if self.address_type == 1:  # IPv4
            self.remote_address = socket.inet_ntoa(await self.reader.read(4))
            self.remote_port = int.from_bytes(await self.reader.read(2), byteorder='big')
            return True

        elif self.address_type == 3:  # FQDN
            fqdn_length = int.from_bytes(await self.reader.read(1), byteorder='big')
            fqdn = await self.reader.read(fqdn_length)
            self.remote_address = fqdn.decode('utf-8')
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

    NAME = "Unnamed Forwarder"

    def __init__(self, listening_host, listening_port, destination_host, destination_port, update_cli):
        self.listening_host = listening_host
        self.listening_port = listening_port
        self.destination_host = destination_host
        self.destination_port = destination_port
        self.update_cli = update_cli
        self.identifier = alphanumeric_identifier()
        self.clients = []


    @staticmethod
    def is_valid_domain(domain: str) -> bool:
        DOMAIN_REGEX = re.compile(
            # Explanation:
            # 1) ^(?=^.{1,253}$) ensures the entire string is max 253 chars.
            # 2) (?!-) and (?!.*-$) can further enforce that no label starts/ends with a hyphen.
            #    The example below is a simpler approach that just ensures each label
            #    doesn’t start with a hyphen, and the final label has at least 2 letters (TLD).
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

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = LocalPortForwarderClient(reader, writer, self.destination_host, self.destination_port, self.messenger)
        self.clients.append(client)
        await client.start()
        self.clients.remove(client)

    def parse_config(self, config):
        """
        Parse the configuration string for a Local Port Forwarder. The expected format is:

            listening_host:listening_port:destination_host:destination_port

        For example:
            "127.0.0.1:8080:10.0.0.5:22"

        Exceptions:
            - All four fields must be provided for a valid configuration.
            - If fewer or more parts are given, or any field is invalid, a warning is displayed and
              this method returns (None, None, None, None).

        Args:
            config (str): The configuration string to parse.

        Returns:
            tuple: A 4-element tuple (listening_host, listening_port, destination_host, destination_port)
            or (None, None, None, None) if the input is invalid.
        """
        parts = config.split(':')

        if len(parts) == 1 or len(parts) == 2:
            raise InvalidConfigError(f'Invalid configuration `{config}`, a {self.NAME} requires a complete configuration.')

        elif len(parts) == 3:
            raise InvalidConfigError(f'Invalid configuration `{config}`, cannot specify destination host without destination port.')

        elif len(parts) == 4:
            listening_host, listening_port, destination_host, destination_port = parts

        else:
            raise ValueError("Invalid configuration format for LocalPortForwarder.")

        if listening_host != '*' and not (self.is_valid_ip(listening_host) or self.is_valid_domain(listening_host)):
            self.update_cli.display(f'The listening host `{listening_host}` does not appear to be a valid ip or domain.', 'warning', reprompt=False)

        if destination_host != '*' and not (self.is_valid_ip(destination_host) or self.is_valid_domain(destination_host)):
            self.update_cli.display(f'The destination host `{destination_host}` does not appear to be a valid ip or domain.', 'warning', reprompt=False)

        if not self.is_valid_port(listening_port):
            self.update_cli.display(f'The listening port `{listening_port}` does not appear to be a valid port.', 'warning', reprompt=False)

        if destination_port != '*' and not self.is_valid_port(destination_port):
            self.update_cli.display(f'The destination port `{destination_port}` does not appear to be a valid port.', 'warning', reprompt=False)

        return listening_host, int(listening_port), destination_host, int(
            destination_port) if destination_port != '*' else destination_port

    async def start(self):
        self.update_cli.display(
            f'Attempting to forward ({self.listening_host}:{self.listening_port}) -> ({self.destination_host}:{self.destination_port}).',
            'information', reprompt=False)
        try:
            self.server = await asyncio.start_server(self.handle_client, self.listening_host, int(self.listening_port))
            self.update_cli.display(
                f'Messenger {self.messenger.identifier} now forwarding ({self.listening_host}:{self.listening_port}) -> ({self.destination_host}:{self.destination_port}).',
                'success', reprompt=False)
            return True
        except OSError as e:
            if e.errno == 98:  # Typically "Address already in use" on Linux
                self.update_cli.display(
                    f"Port {self.listening_port} is already in use on {self.listening_host}.",
                    'error',
                    reprompt=False
                )
            elif e.errno == 99:  # "Cannot assign requested address" (often means invalid host)
                self.update_cli.display(
                    f"Cannot bind to host '{self.listening_host}'—it may be invalid or unreachable.",
                    'error',
                    reprompt=False
                )
            else:
                # Fallback: show a generic error with the system's message
                self.update_cli.display(
                    f"Failed to bind on {self.listening_host}:{self.listening_port}: {e}",
                    'error',
                    reprompt=False
                )

        return False

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

        for client in self.clients:
            if not client.writer.transport.is_closing():
                client.writer.close()
                await client.writer.wait_closed()
        self.update_cli.display(f'Messenger {self.messenger.identifier} has stopped forwarding ({self.listening_host}:{self.listening_port}) -> (*:*).', 'information', reprompt=False)

class SocksProxy(LocalPortForwarder):

    NAME = "Socks Proxy"

    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        self.update_cli = update_cli
        listening_host, listening_port, destination_host, destination_port = self.parse_config(config)
        Forwarder.__init__(self, listening_host, listening_port, '*', '*', update_cli)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = SocksForwarderClient(reader, writer, self.messenger)
        self.clients.append(client)
        await client.start()
        self.clients.remove(client)

    def parse_config(self, config):
        """
        Parse the configuration string for a Socks Proxy with the following input expectations:
        - listening_host:listening_port:destination_host:destination_port
        - Only listening_port is required. If other values are not provided, apply defaults:
            - listening_host defaults to '127.0.0.1'
            - destination_host and destination_port default to '*'

        :param config: Configuration string
        :return: A tuple (listening_host, listening_port, destination_host, destination_port)
        """
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
            raise ValueError("Invalid configuration format for LocalPortForwarder.")

        if listening_host != '*' and not (self.is_valid_ip(listening_host) or self.is_valid_domain(listening_host)):
            self.update_cli.display(f'The listening host `{listening_host}` does not appear to be a valid ip or domain.', 'warning', reprompt=False)

        if destination_host != '*' and not (self.is_valid_ip(destination_host) or self.is_valid_domain(destination_host)):
            self.update_cli.display(f'The destination host `{destination_host}` does not appear to be a valid ip or domain.', 'warning', reprompt=False)

        if not self.is_valid_port(listening_port):
            self.update_cli.display(f'The listening port `{listening_port}` does not appear to be a valid port.', 'warning', reprompt=False)

        if destination_port != '*' and not self.is_valid_port(destination_port):
            self.update_cli.display(f'The destination port `{destination_port}` does not appear to be a valid port.', 'warning', reprompt=False)

        return listening_host, int(listening_port), destination_host, int(
            destination_port) if destination_port != '*' else destination_port



class RemotePortForwarder(Forwarder):

    NAME = "Remote Port Forwarder"

    def __init__(self, messenger, config, update_cli):
        self.messenger = messenger
        self.update_cli = update_cli
        destination_host, destination_port = self.parse_config(config)
        super().__init__('*', '*', destination_host, destination_port, update_cli)

    async def create_client(self, client_identifier):
        try:
            reader, writer = await asyncio.open_connection(self.destination_host, self.destination_port)
            bind_addr, bind_port = writer.get_extra_info('sockname')
            upstream_message = MessageBuilder.initiate_forwarder_client_rep(client_identifier, bind_addr, bind_port, 0, 0)
            await self.messenger.send_upstream_message(upstream_message)
        except:
            self.update_cli.display(f'Remote Port Forwarder {self.identifier} could not connect to {self.destination_host}:{self.destination_port}', 'error')
            upstream_message = MessageBuilder.initiate_forwarder_client_rep(client_identifier, '', 0, 0, 1)
            await self.messenger.send_upstream_message(upstream_message)
            return
        client = ForwarderClient(reader, writer, self.messenger)
        client.identifier = client_identifier
        self.clients.append(client)
        await client.start()
        self.clients.remove(client)

    def parse_config(self, config):
        """
        Parse the configuration string for RemotePortForwarder with the following input expectations:
        - destination_host:destination_port
        - Exceptions:
            - If only a port is given, treat it as the destination_port and default other values.
            - If only an IP is given, treat it as the destination_host and default other values.

        :param config: Configuration string
        :return: A tuple ('*', '*', destination_host, destination_port)
        """
        parts = config.split(':')

        # Default values for RemotePortForwarder
        destination_host = '127.0.0.1'
        destination_port = None

        # Parse configuration based on the number of parts
        if len(parts) == 1:
            # Only a port is provided
            destination_port = parts[0]

        elif len(parts) == 2:
            # IP and port are provided
            destination_host, destination_port = parts

        else:
            self.update_cli.display(f'Invalid configuration `{config}`, a {self.NAME} expects only a destination port or destination host.', 'warning', reprompt=False)

        if destination_host != '*' and not (self.is_valid_ip(destination_host) or self.is_valid_domain(destination_host)):
            self.update_cli.display(f'The destination host `{destination_host}` does not appear to be a valid ip or domain.', 'warning', reprompt=False)

        if destination_port != '*' and not self.is_valid_port(destination_port):
            self.update_cli.display(f'The destination port `{destination_port}` does not appear to be a valid port.', 'warning', reprompt=False)

        return destination_host, int(destination_port)

    async def start(self):
        self.update_cli.display(f'Messenger {self.identifier} now forwarding (*:*) -> ({self.destination_host}:{self.destination_port}).', 'information', reprompt=False)

class InvalidConfigError(Exception):
    """Raised when a provided config string is invalid."""
    pass