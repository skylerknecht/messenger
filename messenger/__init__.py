#!/usr/bin/env python3
import asyncio
import argparse

from messenger import cli
from messenger import server

__version__ = '0.0.0'

banner = f"""
 __  __                                    
|  \/  | ___  ___ ___  ___ _ __   __ _  ___ _ __ 
| |\/| |/ _ \/ __/ __|/ _ \ '_ \ / _` |/ _ \ '__|
| |  | |  __/\__ \__ \  __/ | | | (_| |  __/ |   
|_|  |_|\___||___/___/\___|_| |_|\__, |\___|_|   
by Skyler Knecht and Kevin Clark |___/ v{__version__}
"""


async def main(banner, cli, server):
    print(banner)
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", type=str, default="127.0.0.1",
                        help="IP address the server should listen on. Default is '127.0.0.1'.")
    parser.add_argument("--port", type=int, default=1337,
                        help="Port number the server should listen on. Default is 1337.")
    parser.add_argument("--ssl", nargs=2, metavar=('CERT', 'KEY'), default=None,
                        help="SSL certificate and key files. Expect two strings: path to the certificate and path to "
                             "the key.")
    parser.add_argument("--buffer_size", type=int, default=4096,
                        help="Size of the packet buffer in bytes. Default is 4096. This should match the client's "
                             "buffer_size.")
    args = parser.parse_args()
    messenger_server = server.MessengerServer(address=args.address, port=args.port, ssl=args.ssl)
    asyncio.create_task(messenger_server.start())
    messenger_cli = cli.MessengerCLI(messenger_server)
    await messenger_cli.run()


def run():
    asyncio.run(main(banner, cli, server))


if __name__ == '__main__':
    try:
        asyncio.run(main(banner, cli, server))
    except KeyboardInterrupt:
        print('\rMessenger Server stopped.')