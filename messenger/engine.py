import asyncio
import struct

from messenger.messengers import HTTPMessenger, WebSocketMessenger
from messenger.message import MessageBuilder, MessageParser, CheckInMessage


class Engine:

    name = 'Messenger Engine'

    def __init__(self, messengers, update_cli, encryption_key):
        self.messengers = messengers
        self.update_cli = update_cli
        self.encryption_key = encryption_key

    def _serialize(self, messages):
        data = b''
        for message in messages:
            data += MessageBuilder.serialize_message(self.encryption_key, message)
        return data

    def _deserialize(self, data: bytes):
        messages = []
        while True:
            if len(data) < 8:
                break
            potential_length = struct.unpack('!I', data[4:8])[0]
            if len(data) < potential_length:
                break
            try:
                remaining_data, message = MessageParser.deserialize_message(self.encryption_key, data)
            except Exception:
                break
            messages.append(message)
            data = remaining_data
        return messages

    def _get_messenger(self, messenger_id):
        for messenger in self.messengers:
            if messenger.identifier == messenger_id:
                return messenger
        return None

    def _register(self, messenger):
        self.messengers.append(messenger)
        self.update_cli.display(
            f'{messenger.transport_type} Messenger `{messenger.nickname}` is now connected.',
            'success', display_module='messengers'
        )

    async def checkin_http(self, data, ip, user_agent):
        messages = self._deserialize(data) if data else []
        if not messages or not isinstance(messages[0], CheckInMessage):
            self.update_cli.display(
                'Unable to identify Messenger, the CheckIn message was not present',
                'warning', display_module='handlers'
            )
            return None

        messenger_id = messages[0].messenger_id
        messenger = self._get_messenger(messenger_id)

        if messenger and not isinstance(messenger, HTTPMessenger):
            self.update_cli.display(
                f'Messenger `{messenger_id}` is not an HTTP Messenger, closing connection.',
                'warning', display_module='handlers'
            )
            return None

        if messenger:
            if messenger.check_in_delta > 60:
                self.update_cli.display(
                    f'{messenger.transport_type} Messenger `{messenger.nickname}` has reconnected.',
                    'success', display_module='handlers'
                )
        else:
            messenger = HTTPMessenger(ip, user_agent, self.update_cli, self._serialize)
            if messenger_id:
                messenger.identifier = messenger_id
            else:
                await messenger.send_message_downstream(CheckInMessage(messenger.identifier))
            self._register(messenger)

        messenger.received_bytes += len(data)
        await messenger.process_upstream_messages(messages[1:])
        messenger.check_in()
        return messenger

    async def checkin_ws(self, data, ws, ip, user_agent):
        messages = self._deserialize(data) if data else []
        if not messages or not isinstance(messages[0], CheckInMessage):
            self.update_cli.display(
                'Unable to identify Messenger, the CheckIn message was not present',
                'warning', display_module='handlers'
            )
            return None

        messenger_id = messages[0].messenger_id
        messenger = self._get_messenger(messenger_id)

        if messenger and not isinstance(messenger, WebSocketMessenger):
            self.update_cli.display(
                f'Messenger `{messenger_id}` is not a WebSocket Messenger, closing connection.',
                'warning', display_module='handlers'
            )
            return None

        if messenger:
            await messenger.set_websocket(ws)
            self.update_cli.display(
                f'{messenger.transport_type} Messenger `{messenger.nickname}` has reconnected.',
                'success', display_module='handlers'
            )
        else:
            messenger = WebSocketMessenger(ws, ip, user_agent, self.update_cli, self._serialize)
            if messenger_id:
                messenger.identifier = messenger_id
            else:
                await messenger.send_message_downstream(CheckInMessage(messenger.identifier))
            self._register(messenger)

        await messenger.process_upstream_messages(messages[1:])
        messenger.start_send_loop()
        messenger.check_in()
        return messenger

    async def send_messages_upstream(self, data):
        messages = self._deserialize(data) if data else []
        if not messages:
            return
        if not isinstance(messages[0], CheckInMessage):
            return
        messenger_id = messages[0].messenger_id
        if not messenger_id:
            return
        messenger = self._get_messenger(messenger_id)
        if messenger:
            messenger.received_bytes += len(data)
            await messenger.process_upstream_messages(messages[1:])

    async def get_downstream_messages(self, messenger):
        result = b''
        while not messenger.downstream_messages.empty():
            message = await messenger.downstream_messages.get()
            serialized = self._serialize([message])
            messenger.sent_bytes += len(serialized)
            result += serialized
        return result

