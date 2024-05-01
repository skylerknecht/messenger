import asyncio

from messenger import __version__
from messenger import server

try:
    print('Running Messenger v{}'.format(__version__))
    server = server.MessengerServer()
    asyncio.run(server.start())
except KeyboardInterrupt:
    print('\rMessenger stopped.', end='')
