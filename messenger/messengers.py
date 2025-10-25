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

        self.last_check_in = time.time()

        self.sent_bytes = 0
        self.received_bytes = 0

    async def get_upstream_messages(self):
        self.last_check_in = time.time()
        upstream_messages = b''
        while not self.upstream_messages.empty():
            upstream_messages += await self.upstream_messages.get()

        return upstream_messages

    @property
    def status(self):
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
                for forwarder in self.forwarders:
                    if forwarder.destination_host == destination_host and int(forwarder.destination_port) == destination_port:
                        await forwarder.handle_initiate_forwarder_client_req(message)
                        break
                else:
                    self.update_cli.display(
                        f'Messenger `{self.identifier}` has no Remote Port Forwarder configured '
                        f'for {destination_host}:{destination_port}, denying forward!',
                        'warning'
                    )
                    await self.send_message_upstream(
                        InitiateForwarderClientRep(
                            forwarder_client_id=message.forwarder_client_id,
                            bind_address="0.0.0.0",
                            bind_port=0,
                            address_type=1,
                            reason=2
                        )
                    )

            # 2) Initiate Forwarder Client Response (0x02)
            elif isinstance(message, InitiateForwarderClientRep):
                for scanner in self.scanners:
                    scanner.handle_initiate_forwarder_client_rep(message)
                for forwarder in self.forwarders:
                    await forwarder.handle_initiate_forwarder_client_rep(message)

            # 3) Send Data (0x03)
            elif isinstance(message, SendDataMessage):
                forwarder_client_id = message.forwarder_client_id
                data = message.data

                forwarder_clients = [c for fw in self.forwarders for c in fw.clients]
                for forwarder_client in forwarder_clients:
                    if forwarder_client.identifier == forwarder_client_id:
                        await forwarder_client.send_data(data)
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
    def status(self):
        elapsed = time.time() - self.last_check_in
        if elapsed < 1:
            return f"{elapsed * 1000:.0f}ms delay"
        elif elapsed < 60:
            return f"{elapsed:.0f}s delay"
        elif elapsed < 3600:
            return f"{elapsed / 60:.0f}m delay"
        else:
            return f"{elapsed / 3600:.0f}h delay"

    async def send_message_upstream(self, message):
        self.update_cli.display(
            f'Messenger {self.identifier} queued a upstream message.',
            'debug',
            debug_level = 2
        )
        self.update_cli.display(
            f'Messenger {self.identifier} queued the following upstream message\n{message}.',
            'debug',
            debug_level = 5
        )
        await self.upstream_messages.put(self.serialize_messages([message]))

class WebSocketMessenger(Messenger):

    transport_type = 'WebSocket'

    def __init__(self, websocket, ip, user_agent, update_cli, serialize_messages):
        super().__init__(update_cli, serialize_messages)
        self.ip = ip
        self.user_agent = user_agent
        self.websocket = websocket

    @property
    def status(self):
        if not self.websocket.closed:
            return 'connected'
        return 'disconnected'

    async def set_websocket(self, ws):
        self.websocket = ws
        self.update_cli.display(
            f'{self.transport_type} Messenger `{self.identifier}` has reconnected.',
            'success'
        )
        messages = await self.get_upstream_messages()
        await self.websocket.send_bytes(messages)

    async def send_message_upstream(self, message):
        if self.websocket.closed:
            self.update_cli.display(
                f'Messenger `{self.identifier}` queued a upstream message.',
                'warning'
            )
            await self.upstream_messages.put(self.serialize_messages([message]))
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
