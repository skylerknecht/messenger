import struct
import base64
from typing import Dict, Tuple, List


class MessageParser:
    @staticmethod
    def read_uint32(value: bytes) -> Tuple[int, bytes]:
        """Reads a 32-bit unsigned integer from the beginning of the value and returns the integer and remaining bytes."""
        result = struct.unpack('!I', value[:4])[0]
        return result, value[4:]

    @staticmethod
    def read_string(value: bytes) -> Tuple[str, bytes]:
        """Reads a length-prefixed string from the value and returns the string and remaining bytes."""
        length, value = MessageParser.read_uint32(value)
        result = value[:length].decode('utf-8')
        return result, value[length:]

    @staticmethod
    def header(value: bytes) -> Dict:
        """Parses only the header and returns message type, message length, and remaining value."""
        message_type, value = MessageParser.read_uint32(value)
        message_length, value = MessageParser.read_uint32(value)

        return {
            'Message Type': message_type,
            'Message Length': message_length,
            'Value': value  # Pass remaining value for further parsing as needed
        }

    @staticmethod
    def initiate_forwarder_client_req(value: bytes) -> Dict:
        """Parses the Initiate Forwarder Client Request message, including Forwarder Client ID and IP Address as strings."""
        forwarder_client_id, value = MessageParser.read_string(value)
        ip_address, value = MessageParser.read_string(value)
        port, value = MessageParser.read_uint32(value)
        return {
            'Forwarder Client ID': forwarder_client_id,
            'IP Address': ip_address,
            'Port': port
        }

    @staticmethod
    def initiate_forwarder_client_rep(value: bytes) -> Dict:
        """Parses the Forwarder Client Connected message, including Forwarder Client ID and IP Address as strings."""
        forwarder_client_id, value = MessageParser.read_string(value)
        bind_address, value = MessageParser.read_string(value)
        bind_port, value = MessageParser.read_uint32(value)
        address_type, value = MessageParser.read_uint32(value)
        reason, value = MessageParser.read_uint32(value)
        return {
            'Forwarder Client ID': forwarder_client_id,
            'Bind Address': bind_address,
            'Bind Port': bind_port,
            'Address Type': address_type,
            'Reason': reason
        }

    @staticmethod
    def send_data(value: bytes) -> Dict:
        """Parses the Send Data message, including Forwarder Client ID as a string and Base64-decoded data."""
        forwarder_client_id, value = MessageParser.read_string(value)
        encoded_data, value = MessageParser.read_string(value)  # Reads the Base64 encoded data
        data = base64.b64decode(encoded_data)  # Decodes the data back to original bytes
        return {
            'Forwarder Client ID': forwarder_client_id,
            'Data': data  # Capture original byte data after decoding
        }

    @staticmethod
    def check_in(value: bytes) -> dict:
        """Parses the Check In message, extracting the Messenger ID."""
        messenger_id, _ = MessageParser.read_string(value)
        return {'Messenger ID': messenger_id}


class MessageBuilder:
    @staticmethod
    def header(message_type: int, value: bytes) -> bytes:
        """Builds the message header with a specified type and value."""
        encrypted_value = encrypt(value)
        message_length = 8 + len(encrypted_value)  # Header is 8 bytes, plus value length
        header = struct.pack('!II', message_type, message_length)
        return header + value

    @staticmethod
    def write_string(value: str) -> bytes:
        """Encodes a string with a 4-byte length prefix."""
        encoded_value = value.encode('utf-8')
        return struct.pack('!I', len(encoded_value)) + encoded_value

    @staticmethod
    def initiate_forwarder_client_req(forwarder_client_id: str, ip_address: str, port: int) -> bytes:
        """Creates an Initiate Forwarder Client Request message, including Forwarder Client ID and IP Address as strings."""
        value = (
                MessageBuilder.write_string(forwarder_client_id) +
                MessageBuilder.write_string(ip_address) +
                struct.pack('!I', port)
        )
        return MessageBuilder.header(0x01, value)

    @staticmethod
    def initiate_forwarder_client_rep(forwarder_client_id: str, bind_address: str, bind_port: int, address_type: int,
                                      reason: int) -> bytes:
        """Creates a Forwarder Client Connected message, including Forwarder Client ID and Bind Address as strings."""
        value = (
                MessageBuilder.write_string(forwarder_client_id) +
                MessageBuilder.write_string(bind_address) +
                struct.pack('!III', bind_port, address_type, reason)
        )
        return MessageBuilder.header(0x02, value)

    @staticmethod
    def send_data(forwarder_client_id: str, value: bytes) -> bytes:
        """Creates a Send Data message with variable value length, including Forwarder Client ID as a string.
        The data is base64 encoded before being added to the message."""
        # Base64 encode the data value
        encoded_value = base64.b64encode(value).decode('utf-8')
        message_data = MessageBuilder.write_string(forwarder_client_id) + MessageBuilder.write_string(encoded_value)
        return MessageBuilder.header(0x03, message_data)

    @staticmethod
    def check_in(messenger_id: str) -> bytes:
        """Creates a Check In message, including the Messenger ID."""
        value = MessageBuilder.write_string(messenger_id)
        return MessageBuilder.header(0x04, value)

    @staticmethod
    def build_message_array(messages: List[bytes]) -> bytes:
        """Creates a single byte array from a list of individual message byte arrays."""
        return b''.join(messages)
