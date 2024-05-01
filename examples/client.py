import aiohttp
import asyncio
import base64
import collections
import json
import socket


buffer_size = 4096
uri = '127.0.0.1:1337'
ws_route = 'ws5'
http_route = 'http'

client = collections.namedtuple('Client', 'reader writer')
clients = {}


### HELPERS
def bytes_to_base64(data) -> str:
    """
    Base64 encode a bytes object.
    :param data: A python bytes object.
    :return: A base64 encoded string
    :rtype: str
    """
    return base64.b64encode(data).decode('utf-8')


def base64_to_bytes(data) -> bytes:
    """
    Base64 encode a bytes object.
    :param data: A base64 string.
    :return: A bytes object.
    :rtype: bytes
    """
    return base64.b64decode(data)


### CLIENT

def generate_downstream_msg(identifier, msg: bytes):
    return json.dumps({
        'identifier': identifier,
        'msg': bytes_to_base64(msg),
    })


async def handle_transport_downstream(downstream_msg, transport):
    if isinstance(transport, aiohttp.ClientWebSocketResponse):
        await transport.send_str(downstream_msg)
    async with aiohttp.ClientSession() as session:
        async with session.post(f'http://{uri}/{http_route}', json=downstream_msg) as response:
            messages = await response.text()
            print(messages)


def socks_connect_results(identifier, rep, atype, bind_addr, bind_port):
    return generate_downstream_msg(
        identifier,
        b''.join([
            b'\x05',
            int(rep).to_bytes(1, 'big'),
            int(0).to_bytes(1, 'big'),
            int(1).to_bytes(1, 'big'),
            socket.inet_aton(bind_addr) if bind_addr else int(0).to_bytes(1, 'big'),
            bind_port.to_bytes(2, 'big') if bind_port else int(0).to_bytes(1, 'big')
        ])
    )


async def ws_stream(identifier, ws):
    client = clients[identifier]
    while True:
        msg = await client.reader.read(buffer_size)
        if not msg:
            break
        downstream_msg = generate_downstream_msg(identifier, msg)
        ws.send_str(downstream_msg)


async def http_stream(identifier, uri, http_route):
    client = clients[identifier]
    async with aiohttp.ClientSession() as session:
        while True:
            msg = await client.reader.read(buffer_size)
            if not msg:
                break
            downstream_msg = generate_downstream_msg(identifier, msg)
            async with session.post(f'http://{uri}/{http_route}', json=downstream_msg) as response:
                pass


async def socks_connect(msg):
    identifier = msg.get('identifier')
    atype = msg.get('atype')
    remote = msg.get('address')
    port = int(msg.get('port'))
    print(msg)
    try:
        reader, writer = await asyncio.open_connection(remote, port)
        clients[identifier] = client(reader, writer)
        bind_addr, bind_port = writer.get_extra_info('sockname')
        return socks_connect_results(identifier, 0, atype, bind_addr, bind_port)
    except Exception as e:
        return socks_connect_results(identifier, 1, atype, None, None)


async def start_http_socks5(uri, http_route, socks_server_id):
    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(0.1)
            async with session.post(f'http://{uri}/{http_route}', json=socks_server_id) as response:
                if response.status == 200:
                    messages = await response.text()
                    messages = json.loads(messages)
                    for message in messages:
                        message=json.loads(message)
                        identifier = message.get('identifier', None)
                        if not identifier:
                            continue
                        if identifier in clients:
                            clients[identifier].writer.write(base64_to_bytes(message.get('msg')))
                            continue
                        socks_connect_message = await socks_connect(message)
                        async with session.post(f'http://{uri}/{http_route}', json=socks_connect_message) as response:
                            print(response.status)
                        asyncio.create_task(http_stream(identifier, uri, http_route))
                else:
                    print(f"HTTP POST request failed with status code: {response.status}")


async def main(uri, ws_route, http_route):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f'ws://{uri}/{ws_route}') as ws:
                async for msg in ws:
                    msg = json.loads(msg.json())
                    identifier = msg.get('identifier', None)
                    if not identifier:
                        return
                    if identifier in clients:
                        clients[identifier].writer.write(base64_to_bytes(msg.get('msg')))
                        continue
                    await ws.send_str(await socks_connect(msg))
                    asyncio.create_task(ws_stream(identifier, ws))
    except Exception as e:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://{uri}/{http_route}') as response:
                if response.status == 200:
                    socks_server_id = await response.text()
                    print(socks_server_id)
                    asyncio.create_task(start_http_socks5(uri, http_route, socks_server_id))
                else:
                    print(f"HTTP GET request failed with status code: {response.status}")
        await asyncio.Event().wait()


asyncio.run(main(uri, ws_route, http_route))



