# Messenger

Messenger is a tunneling toolkit that leverages a client-server infrastructure
to establish SOCKS5 proxies, local port forwards and remote port forwards. While 
the server is primarily written in Python, there are several clients written in
varying languages. Their details and major feature support can be 
[found below](https://github.com/skylerknecht/messenger?tab=readme-ov-file#client-support-matrix). 

## Quick Start

To setup Messenger and establish a client connection execute the following commands. 

### Installation
Messenger has a setup.py file that can be ran directly or installed with pipx. 
```
operator~# git clone https://github.com/skylerknecht/messenger.git --recurse-submodules
operator~# cd messenger
operator~/messenger# pipx install .
```

### Launch
Luanching Messenger will output several details that will be leveraged in later commands including
an AES encryption key and server URL. 
```
operator~# messenger-cli
 __  __
|  \/  | ___  ___ ___  ___ _ __   __ _  ___ _ __
| |\/| |/ _ \/ __/ __|/ _ \ '_ \ / _` |/ _ \ '__|
| |  | |  __/\__ \__ \  __/ | | | (_| |  __/ |
|_|  |_|\___||___/___/\___|_| |_|\__, |\___|_|
by Skyler Knecht and Kevin Clark |___/ v0.3.6

[*] The AES encryption key is ZDXgoqyVXqDpJyBMJt
[*] Waiting for messengers on ws+http://0.0.0.0:8080/
```

### Build
Messenger comes with a builder utility to create clients. Leverage the help menu or the 
[client support matrix](https://github.com/skylerknecht/messenger?tab=readme-ov-file#client-support-matrix)
to see builder-supported clients.
```
operator~# messenger-builder python --encryption-key ZDXgoqyVXqDpJyBMJt
Wrote Python client to 'client.py'
```

### Connect
Once a client is built, execute it to connect to the server. Options can typically be hardcoded or overridden 
with command line arguments. 
```
operator~# ./client.py
[+] Connected to http://localhost:8080/socketio/?EIO=4&transport=websocket
```

## Detailed Guides

### Operators
- [Getting Started](docs/getting-started.md)  
- [Operational Usage](docs/operational-usage.md)  


### Developers 
- [Communication Overview](docs/communication.md)


## Client Support Matrix

| Clients                                                            | Messenger Builder | Protocols         | Local/Remote Port Forwarding | SOCKS5 TCP | SOCKS5 UDP    |
|--------------------------------------------------------------------|-------------------|-------------------|------------------------------|------------|---------------|
| [Python](https://github.com/skylerknecht/messenger-client-python)  | Supported         | HTTP & WebSockets | Supported                    | Supported  | Not Supported |
| [C#](https://github.com/skylerknecht/messenger-client-python)      | Not Supported     | HTTP & WebSockets | Supported                    | Supported  | Not Supported |
| [Node JS](https://github.com/skylerknecht/messenger-client-nodejs) | Not Supported     |        WebSockets | Supported                    | Supported  | Not Supported |

## Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)
