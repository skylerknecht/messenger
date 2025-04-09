import socket
import struct

def build_query(domain):
    # Transaction ID, flags, QDCOUNT, ANCOUNT, NSCOUNT, ARCOUNT
    header = struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)

    # Build QNAME
    qname = b"".join(
        (bytes([len(part)]) + part.encode() for part in domain.strip('.').split('.'))
    ) + b"\x00"

    qtype = struct.pack("!H", 1)   # A record
    qclass = struct.pack("!H", 1)  # IN
    question = qname + qtype + qclass

    full_query = header + question

    # TCP requires 2-byte length prefix
    return struct.pack("!H", len(full_query)) + full_query

def send_tcp_dns_query(domain, server="127.0.0.1", port=5053):
    query = build_query(domain)

    with socket.create_connection((server, port)) as s:
        s.sendall(query)

        length_bytes = s.recv(2)
        if len(length_bytes) < 2:
            raise Exception("Short response")

        response_len = struct.unpack("!H", length_bytes)[0]
        response = s.recv(response_len)

        print(f"Received {len(response)} bytes from {server}:{port}")
        print("Raw hex:", response.hex())

        tid = response[:2]
        qdcount = struct.unpack("!H", response[4:6])[0]
        ancount = struct.unpack("!H", response[6:8])[0]

        print(f"Transaction ID: {tid.hex()} | Questions: {qdcount} | Answers: {ancount}")

        # Skip header (12 bytes) and question section
        offset = 12
        while response[offset] != 0:
            offset += response[offset] + 1
        offset += 5  # null + QTYPE (2) + QCLASS (2)

        ip_addresses = []

        for _ in range(ancount):
            offset += 2  # NAME (pointer or full)
            rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", response[offset:offset+10])
            offset += 10
            rdata = response[offset:offset+rdlength]
            offset += rdlength

            if rtype == 1 and rclass == 1 and rdlength == 4:
                ip = ".".join(str(b) for b in rdata)
                ip_addresses.append(ip)

        if ip_addresses:
            print(f"🔍 A Records for {domain}:")
            for ip in ip_addresses:
                print(f" - {ip}")
        else:
            print("No A records found.")

if __name__ == "__main__":
    send_tcp_dns_query("example.com")