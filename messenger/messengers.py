import asyncio
import time

from abc import abstractmethod
from messenger.generator import alphanumeric_identifier
from messenger.message import (
    InitiateForwarderClientReq,
    InitiateForwarderClientRep,
    SendDataMessage
)

class Messenger:

    transport_type = 'undefined'

    def __init__(self, update_cli, serialize_messages):
        self.identifier = alphanumeric_identifier()
        self.update_cli = update_cli
        self.forwarders = []
        self.scanners = []
        self.upstream_messages = asyncio.Queue()
        self.serialize_messages = serialize_messages

        # utility for non-stateful Messengers like HTTP
        self.last_check_in = time.time()

        # Private raw counters
        self.sent_bytes = 0
        self.received_bytes = 0

        asyncio.create_task(self.expiration())


    async def get_upstream_messages(self):
        self.last_check_in = time.time()
        upstream_messages = b''
        while not self.upstream_messages.empty():
            upstream_messages += await self.upstream_messages.get()

        return upstream_messages

    @property
    def alive(self):
        raise NotImplementedError

    @property
    def expiration(self):
        raise NotImplementedError

    @abstractmethod
    async def send_message_upstream(self, message):
        raise NotImplementedError

    @abstractmethod
    async def send_messages_downstream(self, messages):
        self.update_cli.display(
            f'Messenger {self.identifier} received downstream message(s).',
            'debug',
            debug_level = 2
        )
        self.update_cli.display(
            f'Messenger {self.identifier} received the following downstream message(s)\n{messages}.',
            'debug',
            debug_level = 5
        )
        for message in messages:
            # 1) Initiate Forwarder Client Request (0x01)
            if isinstance(message, InitiateForwarderClientReq):
                destination_host = message.ip_address
                destination_port = message.port
                forwarder_client_id = message.forwarder_client_id

                # Find a matching RemotePortForwarder
                for forwarder in self.forwarders:
                    if (forwarder.destination_host == destination_host and
                            int(forwarder.destination_port) == destination_port):
                        # If we have a match, create a new client asynchronously
                        asyncio.create_task(forwarder.create_client(forwarder_client_id))
                        break
                else:
                    # If no break happened, no matching forwarder was found
                    self.update_cli.display(
                        f'Messenger {self.identifier} has no Remote Port Forwarder configured '
                        f'for {destination_host}:{destination_port}, denying forward!',
                        'warning'
                    )

            # 2) Initiate Forwarder Client Response (0x02)
            elif isinstance(message, InitiateForwarderClientRep):
                forwarder_client_id = message.forwarder_client_id
                bind_addr = message.bind_address
                bind_port = message.bind_port
                address_type = message.address_type
                reason = message.reason
                for scanner in self.scanners:
                    scanner.update_result(forwarder_client_id, reason)
                # Search all forwarders’ clients
                forwarder_clients = [c for fw in self.forwarders for c in fw.clients]
                for forwarder_client in forwarder_clients:
                    if forwarder_client.identifier == forwarder_client_id:
                        asyncio.create_task(forwarder_client.connect(bind_addr, bind_port, address_type, reason))
                        break

            # 3) Send Data (0x03)
            elif isinstance(message, SendDataMessage):
                forwarder_client_id = message.forwarder_client_id
                data = message.data

                forwarder_clients = [c for fw in self.forwarders for c in fw.clients]
                for forwarder_client in forwarder_clients:
                    if forwarder_client.identifier == forwarder_client_id:
                        forwarder_client.write(data)
                        break

            # 4) Unknown / Unhandled
            else:
                self.update_cli.display(
                    f"Unknown or unhandled message type: {type(message).__name__}",
                    'information'
                )

    @staticmethod
    def _format_bytes(size: int) -> str:
        """
        Convert an integer number of bytes into a human-friendly string.
        E.g., 1024 -> '1.00 KB', 1234567 -> '1.18 MB'
        """
        if size < 1024:
            return f"{size} B"

        units = ["B", "KB", "MB", "GB", "TB", "PB", "EB"]
        idx = 0
        size_float = float(size)

        while size_float >= 1024 and idx < len(units) - 1:
            size_float /= 1024
            idx += 1

        return f"{size_float:.2f} {units[idx]}"

    def format_sent_bytes(self) -> str:
        """
        Always return a *formatted* string for the bytes sent.
        """
        return self._format_bytes(self.sent_bytes)

    def format_received_bytes(self) -> str:
        """
        Always return a *formatted* string for the bytes received.
        """
        return self._format_bytes(self.received_bytes)


class HTTPMessenger(Messenger):

    transport_type = 'HTTP'

    def __init__(self, ip, user_agent, update_cli, serialize_messages):
        super().__init__(update_cli, serialize_messages)
        self.ip = ip
        self.user_agent = user_agent
        self.disconnected = False

    @property
    def alive(self):
        return not self.disconnected

    async def send_message_upstream(self, message):
        if not self.alive:
            self.update_cli.display(
                f'Messenger {self.identifier} is not alive, cannot send upstream message.',
                'warning'
            )
            return
        self.update_cli.display(
            f'Messenger {self.identifier} sent a upstream message.',
            'debug',
            debug_level = 2
        )
        self.update_cli.display(
            f'Messenger {self.identifier} sent the following upstream message\n{message}.',
            'debug',
            debug_level = 5
        )
        await self.upstream_messages.put(self.serialize_messages([message]))

    async def expiration(self):
        disconnection_rate = 30
        while True:
            await asyncio.sleep(10)
            expired = int(time.time() - self.last_check_in)
            if expired >= disconnection_rate:
                if not self.disconnected:
                    self.disconnected = True
                    self.update_cli.display(
                        f'{self.transport_type} Messenger `{self.identifier}` has not checked in within the past `{disconnection_rate}` seconds and is now set to disconnected.',
                        'warning'
                    )
            else:
                if self.disconnected:
                    self.update_cli.display(
                        f'{self.transport_type} Messenger `{self.identifier}` has reconnected.',
                        'success'
                    )
                self.disconnected = False

class WebSocketMessenger(Messenger):

    transport_type = 'WebSocket'

    def __init__(self, websocket, ip, user_agent, update_cli, serialize_messages):
        super().__init__(update_cli, serialize_messages)
        self.ip = ip
        self.user_agent = user_agent
        self.websocket = websocket

    @property
    def alive(self):
        return not self.websocket.closed

    def set_websocket(self, ws):
        self.websocket = ws
        self.update_cli.display(
            f'{self.transport_type} Messenger `{self.identifier}` has reconnected.',
            'success'
        )
        asyncio.create_task(self.expiration())

    async def expiration(self):
        while True:
            await asyncio.sleep(10)
            if not self.alive:
                self.update_cli.display(
                    f'{self.transport_type} Messenger `{self.identifier}` has disconnected.',
                    'warning'
                )
            break

    async def send_message_upstream(self, message):
        if not self.alive:
            self.update_cli.display(
                f'{self.transport_type} Messenger ({self.identifier}) is not alive, cannot send upstream message.',
                'warning'
            )
            return
        self.update_cli.display(
            f'Messenger {self.identifier} sent a upstream message.',
            'debug',
            debug_level = 2
        )
        self.update_cli.display(
            f'Messenger {self.identifier} sent the following upstream message\n{message}.',
            'debug',
            debug_level = 5
        )
        await self.websocket.send_bytes(self.serialize_messages([message]))
