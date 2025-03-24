import base64
import struct
from collections import namedtuple

# External encryption methods (you already have these in your code)
from messenger.aes import decrypt, encrypt

# ---------------------------
# 1. Named Tuple Definitions
# ---------------------------

CheckInMessage = namedtuple('CheckInMessage', ['messenger_id'])
InitiateForwarderClientReq = namedtuple('InitiateForwarderClientReq', ['forwarder_client_id', 'ip_address', 'port'])
InitiateForwarderClientRep = namedtuple('InitiateForwarderClientRep', ['forwarder_client_id', 'bind_address', 'bind_port', 'address_type', 'reason'])
SendDataMessage = namedtuple('SendDataMessage', ['forwarder_client_id', 'data'])

# You could also store message_type inside each namedtuple, or convert them to @dataclass if you prefer.


# --------------------------------
# 2. MessageParser: Reading Bytes
# --------------------------------

class MessageParser:
    @staticmethod
    def read_uint32(data: bytes) -> (int, bytes):
        """
        Reads the first 4 bytes as an unsigned 32-bit integer (big-endian),
        returns (the_integer, remaining_bytes).
        """
        unsigned_32bit = data[:4]               # The 4-byte integer
        remaining_data = data[4:]               # Everything after the 4 bytes
        (value,) = struct.unpack('!I', unsigned_32bit)
        return value, remaining_data

    @staticmethod
    def read_string(data: bytes) -> (str, bytes):
        """
        Reads a length-prefixed UTF-8 string from data:
          1) read an unsigned 32-bit length
          2) read 'length' bytes as the string
        returns (string, remaining_bytes).
        """
        length, data = MessageParser.read_uint32(data)
        s = data[:length].decode('utf-8')
        return s, data[length:]

    @staticmethod
    def parse_check_in(value: bytes) -> CheckInMessage:
        """
        Given decrypted bytes for a 0x04 message,
        read the messenger_id string into a CheckInMessage.
        """
        messenger_id, _ = MessageParser.read_string(value)
        return CheckInMessage(messenger_id=messenger_id)

    @staticmethod
    def parse_initiate_forwarder_client_req(value: bytes) -> InitiateForwarderClientReq:
        """
        For message type 0x01, parse out:
          - forwarder_client_id (str)
          - ip_address (str)
          - port (uint32)
        """
        forwarder_client_id, value = MessageParser.read_string(value)
        ip_address, value = MessageParser.read_string(value)
        port, value = MessageParser.read_uint32(value)
        return InitiateForwarderClientReq(
            forwarder_client_id=forwarder_client_id,
            ip_address=ip_address,
            port=port
        )

    @staticmethod
    def parse_initiate_forwarder_client_rep(value: bytes) -> InitiateForwarderClientRep:
        """
        For message type 0x02, parse out:
          - forwarder_client_id (str)
          - bind_address (str)
          - bind_port (uint32)
          - address_type (uint32)
          - reason (uint32)
        """
        forwarder_client_id, value = MessageParser.read_string(value)
        bind_address, value = MessageParser.read_string(value)
        bind_port, value = MessageParser.read_uint32(value)
        address_type, value = MessageParser.read_uint32(value)
        reason, value = MessageParser.read_uint32(value)
        return InitiateForwarderClientRep(
            forwarder_client_id=forwarder_client_id,
            bind_address=bind_address,
            bind_port=bind_port,
            address_type=address_type,
            reason=reason
        )

    @staticmethod
    def parse_send_data(value: bytes) -> SendDataMessage:
        """
        For message type 0x03, parse out:
          - forwarder_client_id (str)
          - data (bytes) [ base64-decoded from the stored string ]
        """
        forwarder_client_id, value = MessageParser.read_string(value)
        encoded_data, value = MessageParser.read_string(value)
        raw_data = base64.b64decode(encoded_data)
        return SendDataMessage(
            forwarder_client_id=forwarder_client_id,
            data=raw_data
        )

    @staticmethod
    def deserialize_message(encryption_key: bytes, raw_data: bytes):
        """
        High-level parse entrypoint:
          1) read the message_type (uint32)
          2) read the message_length (uint32)
          3) slice out the encrypted payload
          4) decrypt and parse into an appropriate namedtuple
        Returns (leftover_bytes, parsed_message).
        """
        # 1) Read the message type
        message_type, data = MessageParser.read_uint32(raw_data)

        # 2) Read the message length (which includes header + payload)
        message_length, data = MessageParser.read_uint32(data)

        # 3) The payload is (message_length - 8) bytes (subtracting the 8-byte header)
        payload_len = message_length - 8
        if len(data) < payload_len:
            raise ValueError("Not enough bytes in data for the payload")

        # Extract the encrypted payload + leftover
        payload = data[:payload_len]
        leftover = data[payload_len:]

        # 5) Dispatch to parse the now-decrypted payload
        if message_type == 0x01:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_initiate_forwarder_client_req(decrypted)
        elif message_type == 0x02:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_initiate_forwarder_client_rep(decrypted)
        elif message_type == 0x03:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_send_data(decrypted)
        elif message_type == 0x04:
            parsed_msg = MessageParser.parse_check_in(payload)
        else:
            raise ValueError(f"Unknown message type: {hex(message_type)}")

        return leftover, parsed_msg


# --------------------------------
# 3. MessageBuilder: Creating Bytes
# --------------------------------

class MessageBuilder:
    @staticmethod
    def serialize_message(encryption_key: bytes, msg) -> bytes:
        """
        High-level build entrypoint: accept one of our named tuples and return
        the fully built+encrypted bytes (including message type, length, etc.).
        """
        value = b''
        if isinstance(msg, InitiateForwarderClientReq):
            message_type = 0x01
            value = encrypt(encryption_key, MessageBuilder.build_initiate_forwarder_client_req(
                msg.forwarder_client_id,
                msg.ip_address,
                msg.port
            ))
        elif isinstance(msg, InitiateForwarderClientRep):
            message_type = 0x02
            value = encrypt(encryption_key, MessageBuilder.build_initiate_forwarder_client_rep(
                msg.forwarder_client_id,
                msg.bind_address,
                msg.bind_port,
                msg.address_type,
                msg.reason
            ))
        elif isinstance(msg, SendDataMessage):
            message_type = 0x03
            value = encrypt(encryption_key, MessageBuilder.build_send_data(
                msg.forwarder_client_id,
                msg.data
            ))
        elif isinstance(msg, CheckInMessage):
            message_type = 0x04
            value = MessageBuilder.build_check_in_message(
                msg.messenger_id
            )
        else:
            raise ValueError(f"Unknown message tuple type: {type(msg)}")

        return MessageBuilder.build_message(message_type, value)

    @staticmethod
    def build_message(message_type: int, value: bytes) -> bytes:
        """
        Common routine to build the 8-byte header and append encrypted payload:
          1) 4 bytes: message_type
          2) 4 bytes: total_length (header + payload)
          3) remainder: encrypt(encryption_key, plaintext_value)
        """
        message_length = 8 + len(value)
        header = struct.pack('!II', message_type, message_length)
        return header + value

    @staticmethod
    def build_string(value: str) -> bytes:
        """
        Encodes a string with a 4-byte length prefix, plus the UTF-8 data.
        """
        encoded = value.encode('utf-8')
        return struct.pack('!I', len(encoded)) + encoded

    @staticmethod
    def build_check_in_message(messenger_id: str) -> bytes:
        return MessageBuilder.build_string(messenger_id)

    @staticmethod
    def build_initiate_forwarder_client_req(forwarder_client_id: str,
                                            ip_address: str, port: int) -> bytes:
        """
        Build a 0x01 request with:
         - forwarder_client_id
         - ip_address
         - port
        """
        return (
            MessageBuilder.build_string(forwarder_client_id) +
            MessageBuilder.build_string(ip_address) +
            struct.pack('!I', port)
        )

    @staticmethod
    def build_initiate_forwarder_client_rep(forwarder_client_id: str,
                                            bind_address: str, bind_port: int,
                                            address_type: int, reason: int) -> bytes:
        """
        Build a 0x02 'response' with:
         - forwarder_client_id
         - bind_address
         - bind_port
         - address_type
         - reason
        """
        return (
            MessageBuilder.build_string(forwarder_client_id) +
            MessageBuilder.build_string(bind_address) +
            struct.pack('!III', bind_port, address_type, reason)
        )

    @staticmethod
    def build_send_data(forwarder_client_id: str, data: bytes) -> bytes:
        """
        Build a 0x03 'send_data' message with:
         - forwarder_client_id
         - data (base64-encoded)
        """
        encoded_data = base64.b64encode(data).decode('utf-8')
        return (
            MessageBuilder.build_string(forwarder_client_id) +
            MessageBuilder.build_string(encoded_data)
        )
