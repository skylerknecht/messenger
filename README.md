<p align="center">
  <img src="docs/images/messenger-logo.png" alt="Messenger" width="800">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.10.5-orange" alt="Version">
  <img src="https://img.shields.io/pypi/v/messenger-proxy" alt="PyPI">
  <img src="https://img.shields.io/badge/python->3.8-blue" alt="Python">
  <img src="https://img.shields.io/github/license/skylerknecht/messenger" alt="License">
  <img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fspecterops%2F.github%2Fmain%2Fconfig%2Fshield.json&style=flat" alt="Sponsored by SpecterOps">
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
operator~# messenger-cli -q -e readme
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

### Toggle adaptive polling

`adaptative` turns adaptive polling on and off for the current HTTP messenger, or
for the messenger ID/name supplied as an argument. Adaptive polling is on by default.
When turned off, the server appends a small random data message for an unused TCP
client ID to poll responses when space remains in the batch. Clients discard
the message, but it prevents adaptive polling from backing off while idle.
Run the command again to turn adaptive polling back on. The state is shown in messenger details.

```text
(messenger)~# adaptative dc01
[+] Adaptive polling off for Messenger `dc01`.
```

### Client compatibility

Each client repository declares its target server version in `target-version.txt`.
`messenger-builder` compares this with the installed server version before building:
minor version differences print a warning, major version differences print an error,
and both allow the build to continue. Patch version differences are allowed.
Missing metadata silently skips the check; invalid metadata stops the build.

If a source checkout has no client builders, initialize them with
`messenger-builder update-clients`, or clone using `git clone --recurse-submodules`.

### Display filters

`display` shows the message settings for handlers, messengers, forwarders, and
scanners. A message-type command toggles that type consistently across all four
profiles; add a profile name to change only that profile.

```text
display off
display reset
display debug
display success
display warning
display info
display error
display scanners info
```

`display off` turns off profile messages. `display reset` restores the startup
defaults: debug off, handler warnings off, and other message types on. Tables,
help, and general CLI feedback remain available.

## Detailed Guides

### Operators
- [Setup a SOCKS Proxy or Local Port Forward](docs/local-port-forwards-and-socks.md)
- [Setup a Remote Port Forward](docs/remote-port-forwards.md)
- [Chain Messenger Clients](docs/chaining-messengers.md)
- [Perform NTLMRelay2Self with Messenger](docs/ntlmrelay2self-with-messenger.md)

### Developers
- [Communication Overview](docs/communication.md)
- [The Minimal Client](docs/minimal-client.md)
- [Client Specification (Pseudo-Code)](docs/client.pseudo)


## Clients

| Client    | Description                                                                          |
|-----------|--------------------------------------------------------------------------------------|
| [Python]  | Designed to run anywhere Python 3.6+ is installed.                                   |
| [C#]      | Compiles to a native Windows .NET Framework 4.7.2 executable with no additional dependencies. |
| [Node JS] | Runs standalone with Node or injected into an Electron app.                          |

[Python]: https://github.com/skylerknecht/messenger-client-python
[C#]: https://github.com/skylerknecht/messenger-client-csharp
[Node JS]: https://github.com/skylerknecht/messenger-client-nodejs

## Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)
