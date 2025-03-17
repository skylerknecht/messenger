from messenger.aes import encrypt, decrypt
from messenger.message import MessageBuilder, MessageParser


class Engine:
    def __init__(self, messengers, update_cli, encryption_key):
        self.messengers = messengers
        self.update_cli = update_cli
        self.encryption_key = encryption_key

    def parse_messages(self, data: bytes):
        """Parses a byte array into individual messages, each with its type included."""
        messages = []
        while data:
            # Parse the header to get the message type and length
            header_info = MessageParser.header(data)
            message_type = header_info['Message Type']
            message_length = header_info['Message Length']
            value = header_info['Value']

            # Extract the entire message using the length from the header
            message_data = decrypt(self.encryption_key, value[:message_length - 8])  # Minus header size
            data = value[message_length - 8:]  # Update remaining data

            # Parse based on message type and include the type in the result
            if message_type == 0x01:
                message = MessageParser.initiate_forwarder_client_req(message_data)
                message['Message Type'] = message_type  # Add type to parsed message
                messages.append(message)
            elif message_type == 0x02:
                message = MessageParser.initiate_forwarder_client_rep(message_data)
                message['Message Type'] = message_type
                messages.append(message)
            elif message_type == 0x03:
                message = MessageParser.send_data(message_data)
                message['Message Type'] = message_type
                messages.append(message)
            elif message_type == 0x04:
                message = MessageParser.check_in(message_data)
                message['Message Type'] = message_type
                messages.append(message)

        return messages