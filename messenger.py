import asyncio
import argparse

from messenger import banner
from messenger import server

try:
    print(banner)
    parser = argparse.ArgumentParser()
    # Define command-line arguments
    parser.add_argument("--address", type=str, default="127.0.0.1",
                        help="IP address the server should listen on. Default is '127.0.0.1'.")
    parser.add_argument("--port", type=int, default=1337,
                        help="Port number the server should listen on. Default is 1337.")
    parser.add_argument("--http_route", type=str, default="/http",
                        help="HTTP route. Default is '/http'.")
    parser.add_argument("--ws_route", type=str, default="/ws",
                        help="WebSocket route. Default is '/ws'.")
    parser.add_argument("--ssl", nargs=2, metavar=('CERT', 'KEY'), default=None,
                        help="SSL certificate and key files. Expect two strings: path to the certificate and path to "
                             "the key.")
    parser.add_argument("--buffer_size", type=int, default=4096,
                        help="Size of the packet buffer in bytes. Default is 4096. This should match the client's "
                             "buffer_size.")
    args = parser.parse_args()
    server = server.MessengerServer(address=args.address, port=args.port, http_route=args.http_route,
                                    ws_route=args.ws_route, ssl=args.ssl)
    asyncio.run(server.start())
except KeyboardInterrupt:
    print('\rMessenger Server stopped', end='')
