#!/usr/bin/env python3
import socket
import socketserver
import re


class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class SimpleHTTPProxyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        """
        A slightly enhanced HTTP/WS proxy that:
          - Handles absolute URLs that start with http:// or ws://
          - Handles CONNECT for HTTPS or WSS
          - Forwards data in a simple tunnel if "Upgrade: websocket" or CONNECT is used
          - Lets you proxy to the same machine (localhost or 127.0.0.1).
        """
        try:
            # Read the request line, e.g. "GET http://example.com/path HTTP/1.1"
            request_line = self.rfile.readline().decode('latin-1')
            if not request_line:
                return

            method, url, version = request_line.strip().split()
        except ValueError:
            self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\nMalformed request line.\r\n")
            return

        # Read headers until a blank line
        headers = []
        while True:
            line = self.rfile.readline().decode('latin-1')
            if not line or line.strip() == '':
                break
            headers.append(line)

        # 1) Handle CONNECT (for HTTPS or WSS)
        #    e.g. "CONNECT targethost:443 HTTP/1.1"
        if method.upper() == "CONNECT":
            self.handle_tunnel(url, version, headers)
            return

        # 2) Otherwise, we expect an absolute URL that might be http:// or ws://
        #    e.g. "GET http://127.0.0.1:5000/hello HTTP/1.1" or "GET ws://127.0.0.1:6000/any WS"
        match = re.match(r'^(?:http|ws)://([^/]+)(.*)', url)
        if not match:
            # If you want to allow plain relative requests like "GET /index.html", you'd need more logic.
            self.request.sendall(
                b"HTTP/1.1 400 Bad Request\r\n\r\nThis proxy only handles full URLs beginning with http:// or ws://,\r\n"
                b"or CONNECT tunnels for https/wss.\r\n"
            )
            return

        host_port, path = match.groups()
        if ":" in host_port:
            host, port_str = host_port.split(':', 1)
            port = int(port_str)
        else:
            host = host_port
            port = 80  # default if not specified in URL

        # Rebuild the request line without the scheme and host
        # e.g. "GET /some_path HTTP/1.1"
        new_request_line = f"{method} {path} {version}\r\n"

        # 3) Connect upstream
        try:
            with socket.create_connection((host, port)) as upstream:
                # Send the reconstructed request line
                upstream.sendall(new_request_line.encode('latin-1'))

                # Send all headers
                for header_line in headers:
                    upstream.sendall(header_line.encode('latin-1'))
                # Blank line to end headers
                upstream.sendall(b"\r\n")

                # If there's extra data from the client (POST body, etc.), forward it
                self.forward_remaining_client_data(upstream)

                # Now, read from upstream and forward back to the client
                self.forward_data(upstream)
        except OSError as e:
            err_msg = f"HTTP/1.1 502 Bad Gateway\r\n\r\nProxy Error: {e}\r\n"
            self.request.sendall(err_msg.encode('latin-1'))

    def handle_tunnel(self, connect_hostport, version, headers):
        """
        Minimal CONNECT tunnel handler for HTTPS/WSS.
        E.g. "CONNECT 127.0.0.1:443 HTTP/1.1"
        We connect to that host/port, then just pass bytes in both directions.
        """
        if ":" in connect_hostport:
            host, port_str = connect_hostport.split(":", 1)
            port = int(port_str)
        else:
            host = connect_hostport
            port = 443  # default for HTTPS or WSS

        try:
            upstream = socket.create_connection((host, port))
        except OSError as e:
            self.request.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\n\r\nCannot connect to " + connect_hostport.encode('latin-1') + b"\r\n"
            )
            return

        # A successful CONNECT requires us to send "200 Connection Established"
        connect_response = f"{version} 200 Connection Established\r\n\r\n"
        self.request.sendall(connect_response.encode('latin-1'))

        # Now pass bytes in both directions (tunnel)
        self.tunnel(upstream)

    def tunnel(self, upstream_sock):
        """
        Pump bytes between the client (self.request) and the upstream_sock until one side closes.
        """
        self.request.setblocking(False)
        upstream_sock.setblocking(False)

        try:
            while True:
                # Client -> Upstream
                try:
                    chunk = self.request.recv(4096)
                    if chunk:
                        upstream_sock.sendall(chunk)
                except BlockingIOError:
                    pass
                except OSError:
                    break

                # Upstream -> Client
                try:
                    data = upstream_sock.recv(4096)
                    if data:
                        self.request.sendall(data)
                    else:
                        break
                except BlockingIOError:
                    pass
                except OSError:
                    break
        finally:
            upstream_sock.close()

    def forward_remaining_client_data(self, upstream):
        """
        Read any leftover data from self.request (non-blocking)
        and send it to `upstream`.
        """
        self.request.setblocking(False)
        try:
            while True:
                body_chunk = self.request.recv(4096)
                if not body_chunk:
                    break
                upstream.sendall(body_chunk)
        except BlockingIOError:
            pass
        finally:
            self.request.setblocking(True)

    def forward_data(self, upstream):
        """
        Forward data from upstream -> client until upstream closes.
        """
        while True:
            data = upstream.recv(4096)
            if not data:
                break
            self.request.sendall(data)


def main():
    HOST, PORT = "0.0.0.0", 8080
    print(f"Starting a simple HTTP/WS proxy on {HOST}:{PORT}")
    with ThreadedTCPServer((HOST, PORT), SimpleHTTPProxyHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
