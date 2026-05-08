import asyncio
import base64
import struct
import time
import traceback

from dnslib import DNSRecord, DNSHeader, RR, QTYPE, RCODE, A, TXT

from messenger.messengers import DNSMessenger


# Per-query/response sizing. These are conservative limits that fit comfortably
# under EDNS0 4096-byte UDP responses and under the 253-char FQDN / 63-char
# label hard limits.
TXT_CHUNK_SIZE = 480                      # raw bytes per downstream chunk (TXT mode)
A_RECORDS_PER_CHUNK = 30                  # data A records per chunk (A mode)
A_CHUNK_SIZE = A_RECORDS_PER_CHUNK * 3    # 90 raw bytes per chunk (A mode)
SEND_STATE_TTL = 120                      # stale send-reassembly buffers dropped after N seconds

# Send-ack flag bits, returned as the low byte of the A record 127.0.0.<flags>
ACK_BIT = 0x01
PENDING_BIT = 0x02


def b32encode_nopad(data: bytes) -> str:
    return base64.b32encode(data).decode('ascii').rstrip('=').lower()


def b32decode_nopad(s: str) -> bytes:
    s = s.upper()
    pad = (-len(s)) % 8
    return base64.b32decode(s + ('=' * pad))


def chunk_bytes(data: bytes, size: int):
    if not data:
        return []
    return [data[i:i + size] for i in range(0, len(data), size)]


def split_b32_strings(b32: str, max_len: int = 230):
    """Split a base32 string into ~max_len pieces. TXT supports up to 255-byte
    strings; we leave headroom for safety."""
    if not b32:
        return ['']
    return [b32[i:i + max_len] for i in range(0, len(b32), max_len)]


class DNSProtocol(asyncio.DatagramProtocol):
    def __init__(self, server):
        self.server = server

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.create_task(self.server.handle_datagram(data, addr, self.transport))


class DNSServer:
    """
    DNS C2 transport. Listens for DNS queries delegated to <parent_domain>
    and shuttles encrypted Messenger frames in/out using three query shapes:

      * <b32(checkin)>.<nonce>.i.<parent>            - first-contact (TXT)
      * <a>.<b>.<c>.<seq>.<total>.<sid>.s.<parent>   - uplink (A response)
      * <nonce>.<chunkidx>.<sid>.r.<parent>          - downlink poll (TXT or A)
    """

    def __init__(self, update_cli, messenger_engine, parent_domain: str,
                 ip: str = '0.0.0.0', port: int = 53):
        self.update_cli = update_cli
        self.engine = messenger_engine
        self.parent = parent_domain.lower().rstrip('.')
        self.parent_labels = self.parent.split('.') if self.parent else []
        self.ip = ip
        self.port = port

        # sid -> {'total': int, 'chunks': {seq: bytes}, 'ts': float}
        self.send_state = {}
        # sid -> list[bytes] (chunked downstream data, served by recv polls)
        self.recv_chunks = {}

    async def start(self):
        loop = asyncio.get_event_loop()
        try:
            self.transport, _ = await loop.create_datagram_endpoint(
                lambda: DNSProtocol(self),
                local_addr=(self.ip, self.port),
            )
            self.update_cli.display(
                f"Waiting for messengers on dns://{self.ip}:{self.port}/ (parent: {self.parent})",
                'Information', reprompt=False,
            )
        except OSError:
            self.update_cli.display(
                f'An error prevented the DNS server from starting:\n{traceback.format_exc()}',
                'error', reprompt=False,
            )

    # -----------------------------------------------------------------
    # Datagram entry point
    # -----------------------------------------------------------------

    async def handle_datagram(self, data, addr, transport):
        try:
            request = DNSRecord.parse(data)
        except Exception:
            self.update_cli.display(
                f'DNS server failed to parse a datagram from {addr[0]}.',
                'debug', debug_level=1,
            )
            return

        try:
            reply = await self.dispatch(request, addr)
        except Exception:
            self.update_cli.display(
                f'DNS handler raised an exception:\n{traceback.format_exc()}',
                'error', reprompt=False,
            )
            reply = request.reply()
            reply.header.rcode = RCODE.SERVFAIL

        try:
            transport.sendto(reply.pack(), addr)
        except OSError:
            pass

    async def dispatch(self, request, addr):
        if not request.questions:
            reply = request.reply()
            reply.header.rcode = RCODE.FORMERR
            return reply

        question = request.questions[0]
        qname = str(question.qname).lower().rstrip('.')
        qtype = question.qtype

        labels = qname.split('.') if qname else []
        if not self._matches_parent(labels):
            reply = request.reply()
            reply.header.rcode = RCODE.NXDOMAIN
            return reply

        sub_labels = labels[:-len(self.parent_labels)] if self.parent_labels else labels
        if not sub_labels:
            reply = request.reply()
            reply.header.rcode = RCODE.NXDOMAIN
            return reply

        tag = sub_labels[-1]
        sub_labels = sub_labels[:-1]

        self.update_cli.display(
            f'DNS query {qname} (type {QTYPE[qtype]}) from {addr[0]}.',
            'debug', debug_level=1,
        )

        if tag == 'i':
            return await self.handle_init(request, sub_labels, qtype, addr)
        if tag == 's':
            return await self.handle_send(request, sub_labels, qtype, addr)
        if tag == 'r':
            return await self.handle_recv(request, sub_labels, qtype, addr)

        reply = request.reply()
        reply.header.rcode = RCODE.NXDOMAIN
        return reply

    def _matches_parent(self, labels):
        if not self.parent_labels:
            return False
        if len(labels) <= len(self.parent_labels):
            return False
        return labels[-len(self.parent_labels):] == self.parent_labels

    # -----------------------------------------------------------------
    # Init: <b32(empty CheckIn)>.<nonce>.i.<parent>  (TXT)
    # -----------------------------------------------------------------

    async def handle_init(self, request, sub_labels, qtype, addr):
        reply = request.reply()
        if qtype != QTYPE.TXT:
            reply.header.rcode = RCODE.REFUSED
            return reply

        # sub_labels = [<b32 checkin>, <nonce>] (we only require the checkin label)
        if len(sub_labels) < 2:
            reply.header.rcode = RCODE.FORMERR
            return reply

        try:
            checkin_bytes = b32decode_nopad(sub_labels[0])
            messages = self.engine.deserialize_messages(checkin_bytes)
            checkin = messages[0]
            assigned_id = self.engine.get_messenger_id(checkin) or ''
        except Exception:
            reply.header.rcode = RCODE.FORMERR
            return reply

        existing = self.engine.get_messenger(assigned_id) if assigned_id else None
        if existing and isinstance(existing, DNSMessenger):
            existing.touch(addr[0])
            response_bytes = self.engine.serialize_messages([
                type(checkin)(messenger_id=existing.identifier)
            ])
        else:
            messenger = DNSMessenger(
                addr[0],
                self.update_cli,
                self.engine.serialize_messages,
            )
            if assigned_id:
                messenger.identifier = assigned_id
            response_bytes = self.engine.add_messenger(messenger)

        encoded = b32encode_nopad(response_bytes)
        reply.add_answer(RR(
            rname=request.questions[0].qname,
            rtype=QTYPE.TXT,
            ttl=0,
            rdata=TXT(split_b32_strings(encoded)),
        ))
        return reply

    # -----------------------------------------------------------------
    # Send: <a>.<b>.<c>.<seq>.<total>.<sid>.s.<parent>  (A response)
    # -----------------------------------------------------------------

    async def handle_send(self, request, sub_labels, qtype, addr):
        reply = request.reply()
        if qtype != QTYPE.A:
            reply.header.rcode = RCODE.REFUSED
            return reply

        # We need at least: 1 data label, seq, total, sid (4)
        if len(sub_labels) < 4:
            reply.header.rcode = RCODE.FORMERR
            return reply

        # Tail: ..., seq_hex, total_hex, sid
        try:
            sid = sub_labels[-1]
            total = int(sub_labels[-2], 16)
            seq = int(sub_labels[-3], 16)
            data_labels = sub_labels[:-3]
        except ValueError:
            reply.header.rcode = RCODE.FORMERR
            return reply

        messenger = self.engine.get_messenger(sid)
        if not isinstance(messenger, DNSMessenger):
            reply.header.rcode = RCODE.NXDOMAIN
            return reply

        try:
            chunk = b32decode_nopad(''.join(label for label in data_labels if label))
        except Exception:
            reply.header.rcode = RCODE.FORMERR
            return reply

        messenger.touch(addr[0])
        messenger.received_bytes += len(chunk)

        # Reassembly
        self._gc_send_state()
        state = self.send_state.get(sid)
        if state is None or state.get('total') != total:
            state = {'total': total, 'chunks': {}, 'ts': time.time()}
            self.send_state[sid] = state
        state['chunks'][seq] = chunk
        state['ts'] = time.time()

        if len(state['chunks']) >= total:
            assembled = b''.join(state['chunks'][i] for i in range(total))
            del self.send_state[sid]
            try:
                messages = self.engine.deserialize_messages(assembled)
                # DNS uplink frames do not carry a leading CheckIn (the sid is in
                # the query labels), so dispatch every message.
                await messenger.send_messages_downstream(messages)
            except Exception:
                self.update_cli.display(
                    f'DNS send dispatch raised an exception:\n{traceback.format_exc()}',
                    'error', reprompt=False,
                )

        flags = ACK_BIT
        if self._has_pending_downstream(sid):
            flags |= PENDING_BIT

        reply.add_answer(RR(
            rname=request.questions[0].qname,
            rtype=QTYPE.A,
            ttl=0,
            rdata=A(f'127.0.0.{flags & 0xFF}'),
        ))
        return reply

    # -----------------------------------------------------------------
    # Recv: <nonce>.<chunkidx_hex>.<sid>.r.<parent>  (TXT or A response)
    # -----------------------------------------------------------------

    async def handle_recv(self, request, sub_labels, qtype, addr):
        reply = request.reply()
        if qtype not in (QTYPE.TXT, QTYPE.A):
            reply.header.rcode = RCODE.REFUSED
            return reply

        if len(sub_labels) < 3:
            reply.header.rcode = RCODE.FORMERR
            return reply

        try:
            sid = sub_labels[-1]
            chunkidx = int(sub_labels[-2], 16)
        except ValueError:
            reply.header.rcode = RCODE.FORMERR
            return reply

        messenger = self.engine.get_messenger(sid)
        if not isinstance(messenger, DNSMessenger):
            reply.header.rcode = RCODE.NXDOMAIN
            return reply

        messenger.touch(addr[0])

        chunk_size = TXT_CHUNK_SIZE if qtype == QTYPE.TXT else A_CHUNK_SIZE

        # Materialize on chunkidx == 0 if no cached chunks remain.
        chunks = self.recv_chunks.get(sid)
        if chunkidx == 0 and not chunks:
            data = await messenger.get_upstream_messages()
            if data:
                chunks = chunk_bytes(data, chunk_size)
                self.recv_chunks[sid] = chunks

        chunks = self.recv_chunks.get(sid)
        total = len(chunks) if chunks else 0

        if total == 0:
            return self._build_empty_recv_reply(request, qtype)

        if chunkidx >= total:
            return self._build_empty_recv_reply(request, qtype)

        chunk = chunks[chunkidx]
        messenger.sent_bytes += len(chunk)

        # Clear cache after the last chunk has been served. Lost responses for
        # the final chunk leave the client to recover by polling chunkidx=0
        # again next cycle.
        if chunkidx == total - 1:
            self.recv_chunks.pop(sid, None)

        if qtype == QTYPE.TXT:
            self._add_recv_txt(reply, request, total, chunk)
        else:
            self._add_recv_a(reply, request, total, chunk)

        return reply

    def _build_empty_recv_reply(self, request, qtype):
        reply = request.reply()
        if qtype == QTYPE.TXT:
            reply.add_answer(RR(
                rname=request.questions[0].qname,
                rtype=QTYPE.TXT,
                ttl=0,
                rdata=TXT(['0000']),
            ))
        else:
            reply.add_answer(RR(
                rname=request.questions[0].qname,
                rtype=QTYPE.A,
                ttl=0,
                rdata=A('127.0.0.0'),
            ))
        return reply

    def _add_recv_txt(self, reply, request, total, chunk):
        encoded = b32encode_nopad(chunk)
        strings = [f'{total:04x}'] + split_b32_strings(encoded)
        reply.add_answer(RR(
            rname=request.questions[0].qname,
            rtype=QTYPE.TXT,
            ttl=0,
            rdata=TXT(strings),
        ))

    def _add_recv_a(self, reply, request, total, chunk):
        # Header A record: 127.<total_hi>.<total_lo>.<records_in_chunk>
        records = []
        for i in range(0, len(chunk), 3):
            piece = chunk[i:i + 3].ljust(3, b'\x00')
            seq = (i // 3) & 0xFF
            records.append((seq, piece))
        reply.add_answer(RR(
            rname=request.questions[0].qname,
            rtype=QTYPE.A,
            ttl=0,
            rdata=A(f'127.{(total >> 8) & 0xFF}.{total & 0xFF}.{len(records) & 0xFF}'),
        ))
        for seq, piece in records:
            reply.add_answer(RR(
                rname=request.questions[0].qname,
                rtype=QTYPE.A,
                ttl=0,
                rdata=A(f'{seq}.{piece[0]}.{piece[1]}.{piece[2]}'),
            ))

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _has_pending_downstream(self, sid):
        if self.recv_chunks.get(sid):
            return True
        messenger = self.engine.get_messenger(sid)
        if isinstance(messenger, DNSMessenger):
            return not messenger.upstream_messages.empty()
        return False

    def _gc_send_state(self):
        now = time.time()
        stale = [sid for sid, state in self.send_state.items()
                 if now - state.get('ts', now) > SEND_STATE_TTL]
        for sid in stale:
            del self.send_state[sid]
