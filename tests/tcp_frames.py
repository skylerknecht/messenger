"""Deterministic TCP stream oracle used by the real-client E2E suite.

TCP does not preserve write or packet boundaries.  These helpers therefore send
30 application records through deliberately awkward write boundaries and verify
the reconstructed records, rather than making assertions about network packets.
"""

from __future__ import annotations

import hashlib
import socket
import struct
from dataclasses import dataclass


FRAME_COUNT = 30
MAGIC = b"MSG1"
HEADER = struct.Struct("!4sII32s")
CHUNK_SIZES = (1, 2, 3, 7, 16, 31, 127, 509, 4093, 8191)
PAYLOAD_SIZES = (0, 1, 7, 15, 16, 17, 31, 255, 1023, 4095, 4096, 4097, 8193)


@dataclass(frozen=True)
class Record:
    sequence: int
    payload: bytes


def records(seed: str, count: int = FRAME_COUNT) -> list[Record]:
    output = []
    for sequence in range(count):
        size = PAYLOAD_SIZES[sequence % len(PAYLOAD_SIZES)]
        block = hashlib.sha256(f"{seed}:{sequence}".encode()).digest()
        payload = (block * ((size + len(block) - 1) // len(block)))[:size]
        output.append(Record(sequence, payload))
    return output


def encode(record: Record) -> bytes:
    digest = hashlib.sha256(record.payload).digest()
    return HEADER.pack(MAGIC, record.sequence, len(record.payload), digest) + record.payload


def encoded_stream(seed: str, count: int = FRAME_COUNT) -> bytes:
    return b"".join(encode(record) for record in records(seed, count))


def send_fragmented(sock: socket.socket, data: bytes) -> None:
    """Mix tiny writes and large coalesced writes without assuming boundaries."""
    offset = 0
    index = 0
    while offset < len(data):
        size = CHUNK_SIZES[index % len(CHUNK_SIZES)]
        sock.sendall(data[offset : offset + size])
        offset += size
        index += 1


def receive_exact(sock: socket.socket, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        chunk = sock.recv(min(65536, size - len(output)))
        if not chunk:
            raise EOFError(f"stream closed after {len(output)} of {size} bytes")
        output.extend(chunk)
    return bytes(output)


def decode(data: bytes) -> list[Record]:
    output = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < HEADER.size:
            raise AssertionError(f"truncated frame header at byte {offset}")
        magic, sequence, size, digest = HEADER.unpack_from(data, offset)
        offset += HEADER.size
        if magic != MAGIC:
            raise AssertionError(f"bad frame magic at sequence {sequence}: {magic!r}")
        payload = data[offset : offset + size]
        if len(payload) != size:
            raise AssertionError(f"truncated payload for sequence {sequence}")
        offset += size
        if hashlib.sha256(payload).digest() != digest:
            raise AssertionError(f"payload digest mismatch for sequence {sequence}")
        output.append(Record(sequence, payload))
    return output


def assert_roundtrip(host: str, port: int, seed: str, count: int = FRAME_COUNT) -> dict:
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.settimeout(15)
        return assert_socket_roundtrip(sock, seed, count)


def assert_socket_roundtrip(sock: socket.socket, seed: str, count: int = FRAME_COUNT) -> dict:
    expected = records(seed, count)
    outbound = b"".join(encode(record) for record in expected)
    send_fragmented(sock, outbound)
    inbound = receive_exact(sock, len(outbound))
    actual = decode(inbound)
    if actual != expected:
        expected_sequences = [record.sequence for record in expected]
        actual_sequences = [record.sequence for record in actual]
        raise AssertionError(
            f"record mismatch: expected sequences {expected_sequences}, got {actual_sequences}"
        )
    return {
        "records": len(actual),
        "bytes": sum(len(record.payload) for record in actual),
        "wire_bytes": len(inbound),
        "sha256": hashlib.sha256(inbound).hexdigest(),
    }
