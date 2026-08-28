import asyncio
import time

from abc import abstractmethod
from messenger.generator import alphanumeric_identifier
from messenger.message import (
    InitiateTCPClientReq,
    InitiateTCPClientRep,
    SendDataMessage,
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
        self.downstream_messages = asyncio.Queue()
        self.serialize_messages = serialize_messages
        self.ips = set()

        self.first_seen = time.time()
        self.last_check_in = self.first_seen
        self.check_in_delta = 0

        self.sent_bytes = 0
        self.received_bytes = 0

    def check_in(self):
        now = time.time()
        self.check_in_delta = now - self.last_check_in
        self.last_check_in = now

    @property
    def nickname(self):
        return self._nickname or self.identifier

    @nickname.setter
    def nickname(self, value):
        self._nickname = value

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
        'CheckOutMessage': 7,
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
    async def send_message_downstream(self, message):
        raise NotImplementedError

    @abstractmethod
    async def process_upstream_messages(self, messages):
        self.update_cli.display(
            f'Messenger {self.nickname} received upstream message(s).',
            'debug', display_module='messengers'
        )
        self.update_cli.display(
            f'Messenger {self.nickname} received the following upstream message(s)\n{messages}.',
            'debug', display_module='messengers'
        )
        for message in messages:
            try:
                self.log_message('upstream', message)

                if isinstance(message, InitiateTCPClientReq):
                    await self._handle_tcp_client_req(message)

                elif isinstance(message, InitiateTCPClientRep):
                    await self._handle_tcp_client_rep(message)

                elif isinstance(message, SendDataMessage):
                    await self._handle_send_data(message)

                elif isinstance(message, InitiateBINDRep):
                    await self._handle_bind_rep(message)

                else:
                    self.update_cli.display(
                        f"Unknown or unhandled message type: {type(message).__name__}",
                        'information', display_module='messengers'
                    )
            except Exception as e:
                self.update_cli.display(
                    f'Messenger `{self.nickname}` failed to handle {type(message).__name__}: {e}',
                    'warning', display_module='messengers'
                )

    async def _handle_tcp_client_req(self, message):
        forwarder = next(
            (candidate for candidate in list(self.forwarders)
             if isinstance(candidate, RemotePortForwarder)
             and candidate.listening_host == message.listening_host
             and int(candidate.listening_port) == int(message.listening_port)),
            None
        )
        if forwarder and not forwarder.is_orphan:
            await forwarder.handle_initiate_tcp_client_req(message)
            return
        self.update_cli.display(
            f'Messenger `{self.nickname}` has no configured remote port forward '
            f'for {message.listening_host}:{message.listening_port} -> '
            f'{message.destination_host}:{message.destination_port}, denying forward!',
            'warning', display_module='messengers'
        )
        await self.send_message_downstream(
            InitiateTCPClientRep(
                client_id=message.client_id,
                bind_address="0.0.0.0",
                bind_port=0,
                address_type=1,
                reason=2
            )
        )

    async def _handle_tcp_client_rep(self, message):
        addr = message.bind_address
        if addr and addr not in self.LOOPBACK_ADDRESSES and addr not in self.ips:
            self.ips.add(addr)
            self.update_cli.display(
                f'Messenger `{self.nickname}` has a new interface: {addr}',
                'success', display_module='messengers'
            )
        for scanner in list(self.scanners):
            await scanner.handle_initiate_tcp_client_rep(message)
        for forwarder in list(self.forwarders):
            await forwarder.handle_initiate_tcp_client_rep(message)

    async def _handle_send_data(self, message):
        tcp_clients = [c for fw in self.forwarders for c in fw.clients]
        for tcp_client in tcp_clients:
            if tcp_client.identifier == message.client_id:
                await tcp_client.send_data(message.data)
                return
        self.update_cli.display(
            f'Messenger `{self.nickname}` received data for unknown client `{message.client_id}`.',
            'warning', display_module='messengers'
        )

    BIND_REASONS = {
        1: 'general failure',
        2: 'address already in use',
        3: 'permission denied',
        4: 'address resolution failed',
        5: 'forwarder stopped',
    }

    async def _handle_bind_rep(self, message):
        if message.reason == 0:
            await self._handle_bind_success(message)
        else:
            await self._handle_bind_error(message)

    async def _handle_bind_error(self, message):
        reason_text = self.BIND_REASONS.get(message.reason, f'unknown reason ({message.reason})')
        for i, forwarder in enumerate(self.forwarders):
            if forwarder.identifier == message.bind_id:
                remote_port_forwarder = self.forwarders.pop(i)
                break
        else:
            self.update_cli.display(
                f'Messenger `{self.nickname}` is no longer remote forwarding '
                f'({message.listening_host}:{message.listening_port}): {reason_text}.',
                'information', display_module='messengers'
            )
            return

        remote_port_forwarder.close_all_clients()
        severity = 'information' if message.reason == 5 else 'error'
        self.update_cli.display(
            f'Messenger `{self.nickname}` is no longer remote forwarding '
            f'({message.listening_host}:{message.listening_port}): {reason_text}.',
            severity, display_module='messengers'
        )

    async def _handle_bind_success(self, message):
        remote_port_forwarder = next(
            (forwarder for forwarder in self.forwarders if forwarder.identifier == message.bind_id),
            None
        )
        if remote_port_forwarder:
            remote_port_forwarder.forwarding = True
            dest = f' -> ({remote_port_forwarder.destination_host}:{remote_port_forwarder.destination_port})' if not remote_port_forwarder.is_orphan else ''
            self.update_cli.display(
                f'Messenger `{self.nickname}` is now remote forwarding ({message.listening_host}:{message.listening_port}){dest}.',
                'success', display_module='messengers'
            )
            return

        # Unknown bind_id — the client is listening but the server has no record.
        # Replace any stale entry tracking the same host:port under a different bind_id.
        for i, forwarder in enumerate(self.forwarders):
            if (isinstance(forwarder, RemotePortForwarder)
                    and forwarder.listening_host == message.listening_host
                    and int(forwarder.listening_port) == int(message.listening_port)):
                old_remote_port_forwarder = self.forwarders.pop(i)
                old_remote_port_forwarder.close_all_clients()
                self.update_cli.display(
                    f'Messenger `{self.nickname}` claims bind `{message.bind_id}` on '
                    f'{message.listening_host}:{message.listening_port}, which was tracked as '
                    f'`{old_remote_port_forwarder.identifier}`. Replacing the stale entry.',
                    'warning', display_module='messengers'
                )
                break


        # Store as an orphan with no destination — can't route until the operator
        # runs `remote` to configure where traffic should go.
        remote_port_forwarder = RemotePortForwarder.orphan(
            self, message.bind_id, message.listening_host,
            message.listening_port, self.update_cli
        )
        self.forwarders.append(remote_port_forwarder)
        self.update_cli.display(
            f'Messenger `{self.nickname}` advertised remote port forward `{message.bind_id}` '
            f'on {message.listening_host}:{message.listening_port}.',
            'warning', display_module='messengers'
        )
        self.update_cli.display(
            f'Run `remote {message.listening_host}:{message.listening_port}:<destination_host>:<destination_port>` to configure it.',
            'warning', display_module='messengers'
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
        elapsed = self.check_in_delta
        if elapsed < 1:
            return color_text(f"{elapsed * 1000:.0f}ms delay", "green")
        elif elapsed < 60:
            return color_text(f"{elapsed:.0f}s delay", "yellow")
        elif elapsed < 3600:
            return color_text(f"{elapsed / 60:.0f}m delay", "red")
        else:
            return color_text(f"{elapsed / 3600:.0f}h delay", "red")

    async def send_message_downstream(self, message):
        self.log_message('downstream', message)
        self.update_cli.display(
            f'Messenger {self.nickname} queued a downstream message.',
            'debug',
            display_module='messengers'        )
        self.update_cli.display(
            f'Messenger {self.nickname} queued the following downstream message\n{message}.',
            'debug',
            display_module='messengers'        )
        await self.downstream_messages.put(message)


class WebSocketMessenger(Messenger):

    transport_type = 'WebSocket'

    def __init__(self, websocket, ip, user_agent, update_cli, serialize_messages):
        super().__init__(update_cli, serialize_messages)
        self.ip = ip
        self.ips.add(ip)
        self.user_agent = user_agent
        self.websocket = websocket
        self._send_task = None

    @property
    def status(self):
        if not self.websocket.closed:
            return color_text('connected', "green")
        return color_text('disconnected', 'red')

    def set_websocket(self, ws):
        self.websocket = ws

    def start_send_loop(self):
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
        self._send_task = asyncio.create_task(self._send_loop())

    async def send_message_downstream(self, message):
        self.log_message('downstream', message)
        self.update_cli.display(
            f'Messenger {self.nickname} queued a downstream message.',
            'debug',
            display_module='messengers'        )
        await self.downstream_messages.put(message)

    def _requeue_first(self, message):
        remaining = [message]
        while not self.downstream_messages.empty():
            remaining.append(self.downstream_messages.get_nowait())
        for m in remaining:
            self.downstream_messages.put_nowait(m)

    async def _send_loop(self):
        while True:
            message = await self.downstream_messages.get()
            try:
                serialized = self.serialize_messages([message])
                await self.websocket.send_bytes(serialized)
                self.sent_bytes += len(serialized)
            except Exception:
                self._requeue_first(message)
                break
            except BaseException:
                self._requeue_first(message)
                raise
