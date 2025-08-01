import struct

from messenger.messengers import Messenger, HTTPMessenger
from messenger.message import MessageBuilder, MessageParser, CheckInMessage

class Engine:

    name = 'Messenger Engine'

    transport_type_to_messenger = {
        'http': HTTPMessenger
    }

    def __init__(self, messengers, update_cli, encryption_key):
        self.messengers = messengers
        self.update_cli = update_cli
        self.encryption_key = encryption_key

    def serialize_messages(self, messages):
        data = b''
        for message in messages:
            data += MessageBuilder.serialize_message(self.encryption_key, message)
        return data

    def deserialize_messages(self, data: bytes):
        """
        Parses ALL messages from 'data' until it's exhausted or insufficient
        for another header. Returns a list of (message_type, parsed_message).
        """
        messages = []
        while True:
            # If we don't have at least 8 bytes, we can't read another header
            if len(data) < 8:
                break

            # Peek at the length from the header to see if there's enough payload
            # to parse. We can do a quick check here or just rely on our single parse.
            potential_length = struct.unpack('!I', data[4:8])[0]

            # If the total needed is more than we have, we can't parse further
            if len(data) < potential_length:
                break  # or raise an error if you want strictness

            # Now parse one message
            remaining_data, message = MessageParser.deserialize_message(self.encryption_key, data)
            messages.append(message)
            data = remaining_data

        return messages

    @staticmethod
    def get_messenger_id(message) -> str:
        assert isinstance(message, CheckInMessage)
        return message.messenger_id

    def add_messenger(self, messenger: Messenger):
        self.messengers.append(messenger)
        self.update_cli.display(f'{messenger.transport_type} Messenger `{messenger.identifier}` is now connected.',
                                'success')
        upstream_message = CheckInMessage(messenger.identifier)
        upstream_messages = self.serialize_messages([upstream_message])
        return upstream_messages

    def get_messenger(self, messenger_id):
        for messenger in self.messengers:
            if messenger.identifier == messenger_id:
                return messenger
        return None

    async def send_messages(self, messenger_id: str, messages):
        upstream_messages_data = b''
        for messenger in self.messengers:
            if messenger.identifier == messenger_id:
                await messenger.send_messages_downstream(messages)
                upstream_messages_data += await messenger.get_upstream_messages()
        return upstream_messages_data