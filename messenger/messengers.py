import asyncio
import json
import time

from abc import ABC, abstractmethod
from messenger.message import MessageParser, MessageBuilder


class Messenger(ABC):
    def __init__(self, update_cli):
        self.update_cli = update_cli
        self.alive = True
        self.transport = 'Not Assigned'
        self.forwarders = []

    async def handle_message(self, message):
        # Parse the header to understand the message type
        message_type = message['Message Type']

        # Handle each message type based on protocol
        if message_type == 0x01:  # Initiate Forwarder Client Request
            local_host = message['IP Address']
            local_port = message['Port']
            for forwarder in self.forwarders:
                if forwarder.local_host != local_host or int(forwarder.local_port) != local_port:
                    continue
                asyncio.create_task(forwarder.create_client(message['Forwarder Client ID']))
                return
            self.update_cli.display(f'No Remote Forwarder configured for {local_host}:{local_port}, denying forward!', 'warning')
        elif message_type == 0x02:  # Initiate Forwarder Client Response
            forwarder_client_id = message['Forwarder Client ID']
            forwarder_clients = [client for forwarder in self.forwarders for client in forwarder.clients]
            for forwarder_client in forwarder_clients:
                if forwarder_client.identifier != forwarder_client_id:
                    continue
                forwarder_client.connect(message['Bind Address'], message['Bind Port'], message['Address Type'], message['Reason'])
        elif message_type == 0x03:  # Send Data
            forwarder_client_id = message['Forwarder Client ID']
            forwarder_clients = [client for forwarder in self.forwarders for client in forwarder.clients]
            for forwarder_client in forwarder_clients:
                if forwarder_client.identifier != forwarder_client_id:
                    continue
                forwarder_client.writer.write(message['Data'])
        else:
            self.update_cli.display(f"Unknown message type: {message_type}", 'information')

    @abstractmethod
    async def send_upstream_message(self, upstream_message):
        raise NotImplementedError


class HTTPMessenger(Messenger):
    def __init__(self, update_cli):
        super().__init__(update_cli)
        self.transport = 'HTTP'
        self.upstream_messages = asyncio.Queue()
        self.last_check_in = time.time()
        asyncio.create_task(self.expiration())

    async def get_upstream_messages(self):
        self.last_check_in = time.time()
        upstream_messages = b''
        while not self.upstream_messages.empty():
            upstream_messages += await self.upstream_messages.get()
        return upstream_messages

    async def send_upstream_message(self, upstream_message):
        await self.upstream_messages.put(upstream_message)

    async def expiration(self):
        while True:
            await asyncio.sleep(10)
            expired = int(time.time() - self.last_check_in)
            if expired >= 30:
                self.alive = False
                break
            elif expired >= 25:
                self.update_cli.display(f'Messenger {id(self)} has not checked in and will stop within the next 5 seconds', 'Information')
            elif expired >= 15:
                self.update_cli.display(f'Messenger {id(self)} has not checked in and will stop within the next 15 seconds', 'Information')
            elif expired >= 5:
                self.update_cli.display(f'Messenger {id(self)} has not checked in and will stop within the next 25 seconds', 'Information')


class WSMessenger(Messenger):

    def __init__(self, websocket, update_cli):
        super().__init__(update_cli)
        self.transport = 'Websocket'
        self.websocket = websocket

    async def send_upstream_message(self, upstream_message):
        encrypted_upstream_message = upstream_message  # ToDo Update to Encrypted with AES
        await self.websocket.send_bytes(encrypted_upstream_message)