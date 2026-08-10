import asyncio
import time

from abc import abstractmethod
from messenger.generator import alphanumeric_identifier
from messenger.message import (
    InitiateTCPClientReq,
    InitiateTCPClientRep,
    SendDataMessage,
    InitiateBINDReq,
    InitiateBINDRep
)
from messenger.forwarders import RemotePortForwarder
from messenger.text import color_text

class Messenger:

    transport_type = 'undefined'

    LOOPBACK_ADDRESSES = {'127.0.0.1', '::1', '0.0.0.0'}

    def __init__(self, update_cli, serialize_messages):
        self.identifier = alphanumeric_identifier()
        self._nickname = None
        self.update_cli = update_cli
        self.forwarders = []
        self.scanners = []
        self.upstream_messages = asyncio.Queue()
        self.serialize_messages = serialize_messages
        self.ips = set()

        self.first_seen = time.time()
        self.last_check_in = self.first_seen

        self.sent_bytes = 0
        self.received_bytes = 0

    @property
    def nickname(self):
        return self._nickname or self.identifier

    @nickname.setter
    def nickname(self, value):
        self._nickname = value

    async def get_upstream_messages(self):
        if time.time() - self.last_check_in > 60:
            self.update_cli.display(
                f'{self.transport_type} Messenger `{self.nickname}` has reconnected.',
                'success'
            )
        self.last_check_in = time.time()
        upstream_messages = b''
        while not self.upstream_messages.empty():
            upstream_messages += await self.upstream_messages.get()

        return upstream_messages

    @property
    def status(self):
        raise NotImplementedError

    MESSAGE_TYPE_MAP = {
        'CheckInMessage': 1,
        'InitiateTCPClientReq': 2,
        'InitiateTCPClientRep': 3,
        'SendDataMessage': 4,
        'InitiateBINDReq': 5,
        'InitiateBINDRep': 6,
    }

    def log_message(self, direction, message):
        logger = getattr(self.update_cli, 'logger', None)
        if not logger:
            return
        logging_types = getattr(self.update_cli, 'logging_types', None)
        if logging_types is not None:
            type_id = self.MESSAGE_TYPE_MAP.get(type(message).__name__)
            if type_id not in logging_types:
                return
        logger.record_message(direction, self.identifier, message)

    @abstractmethod
    async def send_message_upstream(self, message):
        raise NotImplementedError

    @abstractmethod
    async def send_messages_downstream(self, messages):
        self.update_cli.display(
            f'Messenger {self.nickname} received downstream message(s).',
            'debug',
            debug_level = 2
        )
        self.update_cli.display(
            f'Messenger {self.nickname} received the following downstream message(s)\n{messages}.',
            'debug',
            debug_level = 5
        )
        for message in messages:
            self.log_message('downstream', message)
            # 1) Initiate TCP Client Request (0x01)
            if isinstance(message, InitiateTCPClientReq):
                # A forwarded connection from a remote port forwarder carries the
                # listening endpoint it came through, so map it to the EXACT RPF
                # rather than guessing by destination. Snapshot the list before
                # awaiting (don't iterate-and-await over shared state).
                forwarder = next(
                    (f for f in list(self.forwarders)
                     if isinstance(f, RemotePortForwarder)
                     and f.listening_host == message.listening_host
                     and int(f.listening_port) == int(message.listening_port)),
                    None
                )
                if forwarder is not None and not forwarder.is_orphan:
                    await forwarder.handle_initiate_tcp_client_req(message)
                else:
                    self.update_cli.display(
                        f'Messenger `{self.nickname}` has no configured remote port forward '
                        f'on {message.listening_host}:{message.listening_port}, denying forward!',
                        'warning'
                    )
                    await self.send_message_upstream(
                        InitiateTCPClientRep(
                            client_id=message.client_id,
                            bind_address="0.0.0.0",
                            bind_port=0,
                            address_type=1,
                            reason=2
                        )
                    )

            # 2) Initiate TCP Client Response (0x02)
            elif isinstance(message, InitiateTCPClientRep):
                addr = message.bind_address
                if addr and addr not in self.LOOPBACK_ADDRESSES and addr not in self.ips:
                    self.ips.add(addr)
                    self.update_cli.display(
                        f'Messenger `{self.nickname}` has a new interface: {addr}',
                        'success'
                    )
                for scanner in self.scanners:
                    await scanner.handle_initiate_tcp_client_rep(message)
                for forwarder in self.forwarders:
                    await forwarder.handle_initiate_tcp_client_rep(message)

            # 3) Send Data (0x03)
            elif isinstance(message, SendDataMessage):
                client_id = message.client_id
                data = message.data

                tcp_clients = [c for fw in self.forwarders for c in fw.clients]
                for tcp_client in tcp_clients:
                    if tcp_client.identifier == client_id:
                        await tcp_client.send_data(data)
                        break

            # 5) Initiate BIND Response (0x06)
            elif isinstance(message, InitiateBINDRep):
                if message.listening_host == '':
                    # GONE — the RPF failed to bind, crashed, or was torn down.
                    # Claim the entry atomically (pop before any await), then RST
                    # its connections. A stop we initiated lands here too, so this
                    # branch must be checked FIRST — an empty host can never be a
                    # re-advertisement.
                    gone = None
                    for i, f in enumerate(self.forwarders):
                        if f.identifier == message.bind_id:
                            gone = self.forwarders.pop(i)
                            break
                    if gone is not None:
                        gone.close_all_clients()
                        self.update_cli.display(
                            f'Messenger `{self.nickname}` remote port forward `{message.bind_id}` '
                            f'is gone; removed and closed its connections.',
                            'warning'
                        )
                else:
                    # PRESENT — the client is listening. Reconcile to its claim.
                    existing = next(
                        (f for f in self.forwarders if f.identifier == message.bind_id),
                        None
                    )
                    if existing is not None:
                        existing.seen_bind_rep = True
                        self.update_cli.display(
                            f'Messenger `{self.nickname}` bound {message.listening_host}:{message.listening_port}.',
                            'success'
                        )
                    else:
                        # Unknown bind_id. Any forwarder we hold on this listening
                        # endpoint is stale (the client is ground truth for what's
                        # actually listening) — replace it, then store an orphan
                        # (empty dest) awaiting `remote` to configure it.
                        stale = None
                        for i, f in enumerate(self.forwarders):
                            if (isinstance(f, RemotePortForwarder)
                                    and f.listening_host == message.listening_host
                                    and int(f.listening_port) == int(message.listening_port)):
                                stale = self.forwarders.pop(i)
                                break
                        if stale is not None:
                            stale.close_all_clients()
                            self.update_cli.display(
                                f'Messenger `{self.nickname}` claims bind `{message.bind_id}` on '
                                f'{message.listening_host}:{message.listening_port}, which was tracked as '
                                f'`{stale.identifier}`; replaced the stale entry.',
                                'warning'
                            )
                        orphan = RemotePortForwarder.orphan(
                            self, message.bind_id, message.listening_host,
                            message.listening_port, self.update_cli
                        )
                        self.forwarders.append(orphan)
                        self.update_cli.display(
                            f'Messenger `{self.nickname}` advertised remote port forward `{message.bind_id}` '
                            f'on {message.listening_host}:{message.listening_port} with no destination; run '
                            f'`remote {message.listening_host}:{message.listening_port}:<destination>` to configure it.',
                            'warning'
                        )

            # Unknown / Unhandled
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
        self.ips.add(ip)
        self.user_agent = user_agent
        self.disconnected = False

    @property
    def status(self):
        elapsed = time.time() - self.last_check_in
        if elapsed < 1:
            return color_text(f"{elapsed * 1000:.0f}ms delay", "green")
        elif elapsed < 60:
            return color_text(f"{elapsed:.0f}s delay", "yellow")
        elif elapsed < 3600:
            return color_text(f"{elapsed / 60:.0f}m delay", "red")
        else:
            return color_text(f"{elapsed / 3600:.0f}h delay", "red")

    async def send_message_upstream(self, message):
        self.log_message('upstream', message)
        self.update_cli.display(
            f'Messenger {self.nickname} queued a upstream message.',
            'debug',
            debug_level = 2
        )
        self.update_cli.display(
            f'Messenger {self.nickname} queued the following upstream message\n{message}.',
            'debug',
            debug_level = 5
        )
        await self.upstream_messages.put(self.serialize_messages([message]))


class WebSocketMessenger(Messenger):

    transport_type = 'WebSocket'

    def __init__(self, websocket, ip, user_agent, update_cli, serialize_messages):
        super().__init__(update_cli, serialize_messages)
        self.ip = ip
        self.ips.add(ip)
        self.user_agent = user_agent
        self.websocket = websocket

    @property
    def status(self):
        if not self.websocket.closed:
            return color_text('connected', "green")
        return color_text('disconnected', 'red')

    async def set_websocket(self, ws):
        self.websocket = ws
        self.update_cli.display(
            f'{self.transport_type} Messenger `{self.nickname}` has reconnected.',
            'success'
        )
        messages = await self.get_upstream_messages()
        if not messages:
            return
        await self.websocket.send_bytes(messages)

    async def send_message_upstream(self, message):
        self.log_message('upstream', message)
        if self.websocket.closed:
            self.update_cli.display(
                f'Messenger `{self.nickname}` queued a upstream message.',
                'warning'
            )
            await self.upstream_messages.put(self.serialize_messages([message]))
            return
        self.update_cli.display(
            f'Messenger {self.nickname} sent a upstream message.',
            'debug',
            debug_level = 2
        )
        self.update_cli.display(
            f'Messenger {self.nickname} sent the following upstream message\n{message}.',
            'debug',
            debug_level = 5
        )
        try:
            await self.websocket.send_bytes(self.serialize_messages([message]))
        except Exception:
            self.update_cli.display(
                f'Messenger `{self.nickname}` queued a upstream message.',
                'warning'
            )
            await self.upstream_messages.put(self.serialize_messages([message]))
