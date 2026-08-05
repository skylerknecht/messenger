<p align="center">
  <img src="docs/images/messenger-logo.png" alt="Messenger" width="600">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.5.0-blue" alt="Version">
  <img src="https://img.shields.io/pypi/v/messenger-proxy" alt="PyPI">
  <img src="https://img.shields.io/badge/python->3.8-blue" alt="Python">
  <img src="https://img.shields.io/github/license/skylerknecht/messenger" alt="License">
</p>

Messenger is a tunneling toolkit that leverages a client-server infrastructure
to establish SOCKS5 proxies, local port forwards, and remote port forwards. While 
the server is primarily written in Python, there are several clients written in
varying languages. Their details and major feature support can be 
[found below](https://github.com/skylerknecht/messenger?tab=readme-ov-file#client-support-matrix). 

## Quick Start

To set up Messenger and establish a client connection, execute the following commands. 

### Installation 

#### From PyPi (recommended)

```
operator~# pip install messenger-proxy
```

#### From Source

```
operator~# git clone https://github.com/skylerknecht/messenger.git --recurse-submodules
operator~# cd messenger
operator~/messenger# pipx install .
```

### Launch
Launching Messenger will output several details that will be leveraged in later commands, including
an AES encryption key and server URL. 
```
operator~# messenger-cli -e readme
(messenger)~#         
 __  __                                    
|  \/  | ___  ___ ___  ___ _ __   __ _  ___ _ __ 
| |\/| |/ _ \/ __/ __|/ _ \ '_ \ / _` |/ _ \ '__|
| |  | |  __/\__ \__ \  __/ | | | (_| |  __/ |   
|_|  |_|\___||___/___/\___|_| |_|\__, |\___|_|   
by Skyler Knecht and Kevin Clark |___/ v0.4.5
[*] The AES encryption key is readme
[*] Waiting for messengers on http+ws://0.0.0.0:8080/
(messenger)~#
```

### Build
Messenger comes with a builder utility to create clients. Leverage the help menu or the 
[client support matrix](https://github.com/skylerknecht/messenger?tab=readme-ov-file#client-support-matrix)
to see builder-supported clients.
```
operator~# messenger-builder python --encryption-key readme
Wrote Python client to 'client.py'
```

### Connect
Once a client is built, execute it to connect to the server. Options can typically be hardcoded or overridden 
with command line arguments. 
```
operator~# ./client.py
[+] Connected to http://localhost:8080/
```

## Detailed Guides

### Operators
- [Setup a SOCKS Proxy or Local Port Forward](docs/local-port-forwards-and-socks.md)
- [Setup a Remote Port Forward](docs/remote-port-forwards.md)
- [Chain Messenger Clients](docs/chaining-messengers.md)
- [Perform NTLMRelay2Self with Messenger](docs/ntlmrelay2self-with-messenger.md)

### Developers
- [Communication Overview](docs/communication.md)
- [Client Specification (Pseudo-Code)](docs/client.pseudo)
- [Testing Checklist](docs/testing.md)
- [Releasing](docs/releasing.md)


## Client Support Matrix

| Clients                                                            | Messenger Builder | Protocols         | Local/Remote Port Forwarding | SOCKS5 TCP | SOCKS5 UDP    |
|--------------------------------------------------------------------|-------------------|-------------------|------------------------------|------------|---------------|
| [Python](https://github.com/skylerknecht/messenger-client-python)  | Supported         | HTTP & WebSockets | Supported                    | Supported  | Not Supported |
| [C#](https://github.com/skylerknecht/messenger-client-csharp)      | Supported         | HTTP & WebSockets | Supported                    | Supported  | Not Supported |
| [Node JS](https://github.com/skylerknecht/messenger-client-nodejs) | Supported         | HTTP & WebSockets | Supported                    | Supported  | Not Supported |

## Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)
