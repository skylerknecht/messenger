import base64
import struct
from collections import namedtuple

# External encryption methods (you already have these in your code)
from messenger.aes import decrypt, encrypt

# ---------------------------
# 1. Named Tuple Definitions
# ---------------------------

CheckInMessage = namedtuple('CheckInMessage', ['messenger_id'])
InitiateTCPClientReq = namedtuple('InitiateTCPClientReq', ['client_id', 'destination_host', 'destination_port', 'listening_host', 'listening_port'], defaults=['', 0])
InitiateTCPClientRep = namedtuple('InitiateTCPClientRep', ['client_id', 'bind_address', 'bind_port', 'address_type', 'reason', 'remote_addr', 'remote_port'], defaults=['', 0])
SendDataMessage = namedtuple('SendDataMessage', ['client_id', 'data'])
InitiateBINDReq = namedtuple('InitiateBINDReq', ['bind_id', 'listening_host', 'listening_port', 'destination_host', 'destination_port'])
InitiateBINDRep = namedtuple('InitiateBINDRep', ['bind_id', 'listening_host', 'listening_port', 'reason'])
CheckOutMessage = namedtuple('CheckOutMessage', [])

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
    def parse_initiate_tcp_client_req(value: bytes) -> InitiateTCPClientReq:
        """
        For message type 0x01, parse out:
          - client_id (str)
          - destination_host (str)
          - destination_port (uint32)
        """
        client_id, value = MessageParser.read_string(value)
        destination_host, value = MessageParser.read_string(value)
        destination_port, value = MessageParser.read_uint32(value)
        # listening_host / listening_port are optional — appended by a remote
        # port forwarder so the server can map the forwarded connection to the
        # exact RPF by its listening endpoint. Absent for server-initiated
        # (SOCKS/local) requests.
        listening_host = ''
        listening_port = 0
        if len(value) > 0:
            listening_host, value = MessageParser.read_string(value)
            listening_port, value = MessageParser.read_uint32(value)
        return InitiateTCPClientReq(
            client_id=client_id,
            destination_host=destination_host,
            destination_port=destination_port,
            listening_host=listening_host,
            listening_port=listening_port
        )

    @staticmethod
    def parse_initiate_tcp_client_rep(value: bytes) -> InitiateTCPClientRep:
        """
        For message type 0x02, parse out:
          - client_id (str)
          - bind_address (str)
          - bind_port (uint32)
          - address_type (uint32)
          - reason (uint32)
        """
        client_id, value = MessageParser.read_string(value)
        bind_address, value = MessageParser.read_string(value)
        bind_port, value = MessageParser.read_uint32(value)
        address_type, value = MessageParser.read_uint32(value)
        reason, value = MessageParser.read_uint32(value)
        remote_addr = ''
        remote_port = 0
        if len(value) > 0:
            remote_addr, value = MessageParser.read_string(value)
            remote_port, value = MessageParser.read_uint32(value)
        return InitiateTCPClientRep(
            client_id=client_id,
            bind_address=bind_address,
            bind_port=bind_port,
            address_type=address_type,
            reason=reason,
            remote_addr=remote_addr,
            remote_port=remote_port
        )

    @staticmethod
    def parse_send_data(value: bytes) -> SendDataMessage:
        client_id, value = MessageParser.read_string(value)
        encoded_data, value = MessageParser.read_string(value)
        raw_data = base64.b64decode(encoded_data)
        return SendDataMessage(
            client_id=client_id,
            data=raw_data
        )

    @staticmethod
    def parse_initiate_bind_req(value: bytes) -> InitiateBINDReq:
        bind_id, value = MessageParser.read_string(value)
        listening_host, value = MessageParser.read_string(value)
        listening_port, value = MessageParser.read_uint32(value)
        destination_host, value = MessageParser.read_string(value)
        destination_port, value = MessageParser.read_uint32(value)
        return InitiateBINDReq(
            bind_id=bind_id,
            listening_host=listening_host,
            listening_port=listening_port,
            destination_host=destination_host,
            destination_port=destination_port
        )

    @staticmethod
    def parse_initiate_bind_rep(value: bytes) -> InitiateBINDRep:
        bind_id, value = MessageParser.read_string(value)
        listening_host, value = MessageParser.read_string(value)
        listening_port, value = MessageParser.read_uint32(value)
        reason, value = MessageParser.read_uint32(value)
        return InitiateBINDRep(
            bind_id=bind_id,
            listening_host=listening_host,
            listening_port=listening_port,
            reason=reason
        )

    @staticmethod
    def deserialize_message(encryption_key: bytes, raw_data: bytes):
        message_type, data = MessageParser.read_uint32(raw_data)
        message_length, data = MessageParser.read_uint32(data)

        payload_len = message_length - 8
        if payload_len < 0:
            raise ValueError(f"Invalid message_length {message_length}, must be at least 8")
        if len(data) < payload_len:
            raise ValueError("Not enough bytes in data for the payload")

        payload = data[:payload_len]
        leftover = data[payload_len:]

        if message_type == 0x01:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_initiate_tcp_client_req(decrypted)
        elif message_type == 0x02:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_initiate_tcp_client_rep(decrypted)
        elif message_type == 0x03:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_send_data(decrypted)
        elif message_type == 0x04:
            parsed_msg = MessageParser.parse_check_in(payload)
        elif message_type == 0x05:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_initiate_bind_req(decrypted)
        elif message_type == 0x06:
            decrypted = decrypt(encryption_key, payload)
            parsed_msg = MessageParser.parse_initiate_bind_rep(decrypted)
        elif message_type == 0x07:
            parsed_msg = CheckOutMessage()
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
        if isinstance(msg, InitiateTCPClientReq):
            message_type = 0x01
            value = encrypt(encryption_key, MessageBuilder.build_initiate_tcp_client_req(
                msg.client_id,
                msg.destination_host,
                msg.destination_port,
                msg.listening_host,
                msg.listening_port
            ))
        elif isinstance(msg, InitiateTCPClientRep):
            message_type = 0x02
            value = encrypt(encryption_key, MessageBuilder.build_initiate_tcp_client_rep(
                msg.client_id,
                msg.bind_address,
                msg.bind_port,
                msg.address_type,
                msg.reason,
                msg.remote_addr,
                msg.remote_port
            ))
        elif isinstance(msg, SendDataMessage):
            message_type = 0x03
            value = encrypt(encryption_key, MessageBuilder.build_send_data(
                msg.client_id,
                msg.data
            ))
        elif isinstance(msg, CheckInMessage):
            message_type = 0x04
            value = MessageBuilder.build_check_in_message(
                msg.messenger_id
            )
        elif isinstance(msg, InitiateBINDReq):
            message_type = 0x05
            value = encrypt(encryption_key, MessageBuilder.build_initiate_bind_req(
                msg.bind_id,
                msg.listening_host,
                msg.listening_port,
                msg.destination_host,
                msg.destination_port
            ))
        elif isinstance(msg, InitiateBINDRep):
            message_type = 0x06
            value = encrypt(encryption_key, MessageBuilder.build_initiate_bind_rep(
                msg.bind_id,
                msg.listening_host,
                msg.listening_port,
                msg.reason
            ))
        elif isinstance(msg, CheckOutMessage):
            message_type = 0x07
            value = b''
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
    def build_initiate_tcp_client_req(client_id: str,
                                      destination_host: str, destination_port: int,
                                      listening_host: str = '', listening_port: int = 0) -> bytes:
        result = (
            MessageBuilder.build_string(client_id) +
            MessageBuilder.build_string(destination_host) +
            struct.pack('!I', destination_port)
        )
        # Only a remote port forwarder appends its listening endpoint; empty
        # host means "not an RPF request" so nothing is appended.
        if listening_host:
            result += MessageBuilder.build_string(listening_host) + struct.pack('!I', listening_port)
        return result

    @staticmethod
    def build_initiate_tcp_client_rep(client_id: str,
                                      bind_address: str, bind_port: int,
                                      address_type: int, reason: int,
                                      remote_addr: str = '', remote_port: int = 0) -> bytes:
        result = (
            MessageBuilder.build_string(client_id) +
            MessageBuilder.build_string(bind_address) +
            struct.pack('!III', bind_port, address_type, reason)
        )
        if remote_addr:
            result += MessageBuilder.build_string(remote_addr) + struct.pack('!I', remote_port)
        return result

    @staticmethod
    def build_send_data(client_id: str, data: bytes) -> bytes:
        encoded_data = base64.b64encode(data).decode('utf-8')
        return (
            MessageBuilder.build_string(client_id) +
            MessageBuilder.build_string(encoded_data)
        )

    @staticmethod
    def build_initiate_bind_req(bind_id: str, listening_host: str,
                                listening_port: int, destination_host: str,
                                destination_port: int) -> bytes:
        return (
            MessageBuilder.build_string(bind_id) +
            MessageBuilder.build_string(listening_host) +
            struct.pack('!I', listening_port) +
            MessageBuilder.build_string(destination_host) +
            struct.pack('!I', destination_port)
        )

    @staticmethod
    def build_initiate_bind_rep(bind_id: str, listening_host: str,
                                listening_port: int, reason: int) -> bytes:
        return (
            MessageBuilder.build_string(bind_id) +
            MessageBuilder.build_string(listening_host) +
            struct.pack('!II', listening_port, reason)
        )
