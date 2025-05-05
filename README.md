# Messenger

Messenger is a tunneling toolkit that enables operators to move data 
evasively from one place to another. It supports three industry-standard 
tunneling methods: local port forwarding, remote port forwarding, and 
SOCKS5 proxying. To achieve this, Messenger leverages a client-server 
architecture while communicating over HTTP, WebSockets, and DNS. While 
the server is written primarily in Python, Messenger currently supports 
clients in C#, Python, and Node JS. 


### Installation

To install Messenger, clone the repository with `git` and install with `pipx`. 

```
git clone --recurse-submodules https://github.com/skylerknecht/messenger.git
cd Messenger
pipx install .
```

### Usage Guide

Please review the following guides for a in-depth usage guide.

- [Getting Started](docs/getting-started.md)  
- [Operational Usage](docs/operational-usage.md)  

For developers feel free to review the communication specification below.

- [Communications Overview](docs/communications.md)

### Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)