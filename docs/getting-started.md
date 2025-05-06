# Getting Started

Messenger is a proxy tool designed to be used by penetration testers and red teams. It supports both forward and reverse proxying capabilties and tunnels traffic over HTTP and WebSockets. Anyone already familiar with [Chisel](https://github.com/jpillora/chisel) or [Ligolo](https://github.com/nicocha30/ligolo-ng) should be able to pick up Messenger quickly.

### Do we really need another proxy tool?

Yes, we do. Existing proxy tools either have unfixable design problems or are written in languages unsuitable for operations, such as GoLang.

### Setup Instructions

Clone this github repo **recursively** to download the tool. Messenger requires Python 3.9+

```
git clone --recurse-submodules https://github.com/skylerknecht/messenger.git
```

Use the `setup.py` script to install both `messenger-cli` and `messenger-client`.

```
python3 setup.py install
```
You should then be able to run the `messenger-cli`.

Alternately, install the requirements, then you can use python3 to run the `messenger-cli` file directly:

```
pip3 install -r requirements
python3 messenger-cli
```

### Starting the server

Messenger is designed with sensible defaults in mind. You should just be able to run `messenger-cli` to start the server on port 8080. If you need to tweak server behavior, the following options are supported for the server:
```
$ messenger-cli -h
usage: messenger-cli [-h] [-a ADDRESS] [-p PORT] [-s CERT KEY] [-e ENCRYPTION_KEY] [-q]

optional arguments:
  -h, --help            show this help message and exit
  -a ADDRESS, --address ADDRESS
                        IP address the server should listen on. Default is '0.0.0.0'.
  -p PORT, --port PORT  Port number the server should listen on. Default is 8080.
  -s CERT KEY, --ssl CERT KEY
                        SSL certificate and key files. Expects two strings: path to the certificate and path to the key.
  -e ENCRYPTION_KEY, --encryption-key ENCRYPTION_KEY
                        The AES encryption key.
  -q, --quiet           Suppress the banner.
```

Messenger will list some configurations when it starts up:
```
 __  __
|  \/  | ___  ___ ___  ___ _ __   __ _  ___ _ __
| |\/| |/ _ \/ __/ __|/ _ \ '_ \ / _` |/ _ \ '__|
| |  | |  __/\__ \__ \  __/ | | | (_| |  __/ |
|_|  |_|\___||___/___/\___|_| |_|\__, |\___|_|
by Skyler Knecht and Kevin Clark |___/ v0.2.5

[*] The AES encryption key is ZDXgoqyVXqDpJyBMJt
[*] Waiting for messengers on ws+http://0.0.0.0:8080/
```

### Getting a messenger connected

After the server is started, the next step is to connect a **messenger client**, refered to as a **messenger** for short.

The messenger client is written in two (2) different languages: [C#](https://github.com/skylerknecht/messenger-client-python),
[Python](https://github.com/skylerknecht/messenger-client-python), and Node JS. Which one you use will depend on your operational needs. In this example, the Python client is used.

Messenger supports a build command that can be leveraged to build a messenger client. 

```
(messenger)~# build python
[+] Saved python client as messenger-client.py
```

You need to specify at least two (2) arguments to the messenger client: The location of the messenger server and the encryption key. This could look like the following command:
```
python3 messenger-client.py 192.168.1.100:8080 ZDXgoqyVXqDpJyBMJt
```
Other options can be specified to change some messenger client behaviors, such as remote forward configurations and whether traffic should use an outgoing HTTP proxy.

```
$ python3 messenger-client.py -h
usage: messenger-client [-h] [--proxy PROXY] [--continue-after-success] server_url encryption_key [remote_port_forwards ...]

Messenger Client for establishing HTTP or WebSocket connections with remote port forwarding.

positional arguments:
  server_url            The URL of the server to connect to. This should include the scheme (e.g. ws://, wss://, http://, https://) and the domain or IP address. For example:
                        'ws://example.com' or 'https://example.com'. If no scheme is provided, it will try 'ws', 'wss', 'http', and 'https'.
  encryption_key        The AES encryption key to use for encryption.
  remote_port_forwards  A list of remote port forwarding configurations. Each configuration should be in the format 'listening_host:listening_port:destination_host:destination_port'. For
                        example: '127.0.0.1:8080:example.com:80'. This sets up port forwarding from a local listening address and port to a remote destination address and port.

options:
  -h, --help            show this help message and exit
  --proxy PROXY         Optional proxy server URL.
  --continue-after-success
                        If a attempt were to fail after being successfully connected, continue trying other schemas.
```
If you did everything right, a new messenger should have connected.

```
[+] WebSocket Messenger `mdPZqLZIoN` is now connected.
```
In the Messenger Server console, use the `messengers` command to display a list of all currently registered Messenger clients.
```
(messenger)~# messengers
                           Messengers
  Identifier     Transport    Alive  Forwarders  Sent   Received
-------------- ------------- ------- ---------- ------- --------
  mdPZqLZIoN     WebSocket     Yes      •••       0 B     0 B
```

### Next steps

Congratulations! You've completed the basics of setting up Messenger. The next steps for configuration can be found in operational usage. Many readers may be particularily interested in setting up a SOCKS proxy.
