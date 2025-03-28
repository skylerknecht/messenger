import asyncio
import struct
import socket

# Support multiple A records per domain
A_RECORDS = {
    "example.com.": ["93.184.216.34", "93.184.216.35", "93.184.216.3dqwdqwdqw6"]
}

def parse_question(data):
    offset = 12
    labels = []
    while True:
        length = data[offset]
        if length == 0:
            offset += 1
            break
        labels.append(data[offset + 1:offset + 1 + length].decode())
        offset += 1 + length
    qname = ".".join(labels) + "."
    qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])
    offset += 4
    return qname, qtype, qclass, offset

def build_response(query):
    tid = query[:2]
    flags = b'\x81\x80'  # Standard response
    qdcount = b'\x00\x01'

    qname, qtype, qclass, offset = parse_question(query)
    question = query[12:offset]

    answers = b""
    count = 0

    if qtype == 1 and qclass == 1 and qname in A_RECORDS:
        for ip_str in A_RECORDS[qname]:
            ip = socket.inet_aton(ip_str)
            answers += b'\xc0\x0c'  # Pointer to domain
            answers += struct.pack("!HHI", 1, 1, 300)  # TYPE A, CLASS IN, TTL
            answers += struct.pack("!H", 4) + ip
            count += 1

    ancount = struct.pack("!H", count)
    nscount = b'\x00\x00'
    arcount = b'\x00\x00'
    header = tid + flags + qdcount + ancount + nscount + arcount

    return header + question + answers if count > 0 else None

async def handle_client(reader, writer):
    try:
        length_bytes = await reader.readexactly(2)
        msg_len = struct.unpack("!H", length_bytes)[0]
        data = await reader.readexactly(msg_len)
        addr = writer.get_extra_info('peername')
        print(f"DNS Query from {addr}")

        response = build_response(data)
        if response:
            writer.write(struct.pack("!H", len(response)) + response)
            await writer.drain()
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        print(f"Error: {e}")

async def main():
    server = await asyncio.start_server(handle_client, host="0.0.0.0", port=5053)
    print("DNS TCP server running on port 5053")
    async with server:
        await server.serve_forever()

asyncio.run(main())
