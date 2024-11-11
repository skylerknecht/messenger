# Messenger

Messenger uses a client-server architecture to establish one or more forwarders to allow operators to interact with the local network the client is connected to. 
Two clients exist in Python and C# for cross-platform deployment. The clients use either WebSockets or HTTP to communicate with the server depending on which one 
is available. The server and clients are written in an asynchronous model to support large bandwidths such as network scanning. There are three primary use cases 
of Messenger. These include, within a C2 that supports execute-assembly but not SOCKS5, a C2 that only supports synchronous HTTP SOCKS5, or within an environment 
where HTTP must be used since the environment’s proxy does not support WebSockets. 

### Installation

Messenger comes with a setup.py configured for pipx. Alternatively, using `pip` to install the requirements.txt file will also work.

```
skyler.knecht@debian~# pipx install git+https://github.com/skylerknecht/messenger 
installed package messenger 0.2.2, installed using Python 3.12.3
These apps are now globally available
    - messenger-client
    - messenger-server
skyler.knecht@debian~# pipx ensurepath # Make sure pipx is added to your path
skyler.knecht@debian~# messenger-server

 __  __                                    
|  \/  | ___  ___ ___  ___ _ __   __ _  ___ _ __ 
| |\/| |/ _ \/ __/ __|/ _ \ '_ \ / _` |/ _ \ '__|
| |  | |  __/\__ \__ \  __/ | | | (_| |  __/ |   
|_|  |_|\___||___/___/\___|_| |_|\__, |\___|_|   
by Skyler Knecht and Kevin Clark |___/ v0.1.2

[*] The AES encryption key is nxmfLCBUfQjsb
[*] Waiting for messengers on http+ws://172.16.100.2:1337/
(messenger)~# 
```



# Usage Guide

## Messenger Server

The **messenger-server** provides a WebSocket or HTTP server for messengers to connect, enabling SOCKS proxies and local or remote port forwarding.

### Starting the Server

Run the server with the following command:

```
./messenger-server
```

### Optional Arguments

- **`--address ADDRESS`**: IP address the server should listen on. Default is `127.0.0.1`.
- **`--port PORT`**: Port number the server should listen on. Default is `1337`.
- **`--ssl CERT KEY`**: SSL certificate and key files. Provide two paths: the certificate file and the key file.
- **`-q, --quiet`**: Suppresses the banner from being displayed.
- **`-h, --help`**: Displays the help message and exits.

### Example Commands

1. Run the server with default settings:
   ```
   ./messenger-server
   ```

2. Run the server on a specific address and port:
   ```
   ./messenger-server --address 192.168.1.100 --port 8080
   ```

3. Run the server with SSL encryption:
   ```
   ./messenger-server --ssl /path/to/cert.pem /path/to/key.pem
   ```

4. Suppress the banner on startup:
   ```
   ./messenger-server -q
   ```

---

## Messenger Client

The **messenger-client** connects to the server and establishes port forwarding.

### Starting the Client

Run the client with the following command:

```
./messenger-client <uri> <encryption_key> [remote_port_forwards ...]
```

- **`<uri>`**: Server URI that includes the scheme and address (e.g., `http://<SERVER_IP>:<PORT>`). The client supports a fallback mechanism, allowing a URI like `http+ws+wss://127.0.0.1:1337`. This attempts to connect sequentially using `http`, `ws`, and `wss` if the previous protocol fails.
- **`<encryption_key>`**: AES encryption key used for communication.
- **`[remote_port_forwards ...]`**: Optional remote port forwarding configurations in the format `<listening_host>:<listening_port>:<destination_host>:<destination_port>`.

Example:

```
./messenger-client https+wss+http://192.168.1.100:1337 dNdZeuBRYEu
[-] Failed to connect to https://192.168.1.100:1337/
[-] Failed to connect to wss://192.168.1.100:1337/
[+] Successfully connected to http://192.168.1.100:1337/socketio/?EIO=4&transport=polling
```

### Optional Arguments

- **`--proxy <PROXY>`**: Specify a proxy server for connecting to the messenger-server.

---

### Example Workflow

1. Start the server:
   ```
   ./messenger-server --address 172.16.100.2
   ```
2. Connect a client:
   ```
   ./messenger-client http://172.16.100.2:1337 VFLlgWdrfmArqFTKWV 127.0.0.1:8080:127.0.0.1:8081
   ```
3. View connected messengers:
   ```
   (messenger)~# messengers
   ```
4. Set up forwarders:
   ```
   (messenger)~# local 127.0.0.1:8082:127.0.0.1:8081 nxMIuiFWpi
   (messenger)~# remote 8081 nxMIuiFWpi
   ```


### Messenger Client (C#)

The Messenger Client exists in Python and C#. The C# version lives on a separate [GitHub repository](https://github.com/skylerknecht/messenger-client). 
All the same arguments as discussed above apply. The client is written in .NET Framework and uses dnMerge to statically compile all it's dependencies.  

### Proxychains and Network Scanning 

Network scanning with tools such as nmap may cause issues if the timeout is too high. This is primarily due to 
the single-connection nature that nmap operates with. Having said, please ensure you're using the TCP connect flag `-sT` 
and use the following proxychains configuration.

```
# proxychains.conf  VER 4.x
quiet_mode
proxy_dns
remote_dns_subnet 224
tcp_read_time_out 15000 #Defaults to 150,000
tcp_connect_time_out 10000
socks5 127.0.0.1 9050
```

### Debugging [Currently Unavailable]

To identify what may be causing issues Messenger Server supports a debug command. 
The debug command will alter that status level permitting Messenger Server to output verbose status messages. 


|       Status Level        |              Description               |
|:-------------------------:|:--------------------------------------:|
|             0             | Only show the standard status messages |
|             1             |          Connection attempts           |   
|             2             |     Upstream and Downstream data.      |

The operator should be able to determine if it's a client or server issue with the following two scenarios.

In the scenario you're not receiving any connection attempts, level 1 status messages, the SOCKS5 server is either not 
listening, you're using a version of SOCKS that's not supported, or you cannot connect to the SOCKS5 port. 

In the scenario you're receiving connection attempts with no level 2 messages then the client either did not receive 
the connection attempt or did not have the ability to respond. 

Below is an example of a successful connection attempt and upstream/downstream messages.

```
skyler.knecht@debian~# messegner-server -q
Welcome to the Messenger CLI, type exit or socks.
[*] Messenger Server is running on http+ws://172.16.100.2:1337/
[+] Socks Server (WS) on port 9707 has started
(messenger)~# debug 2
[*] Set current status level to 2
[DBG]-1 Connecting to 172.16.110.201:3389
[DBG]-2 Receiving 10 byte(s) from 172.16.110.201:3389
[DBG]-2 Sending 51 byte(s) to 172.16.110.201:3389
[DBG]-2 Receiving 19 byte(s) from 172.16.110.201:3389
[DBG]-2 Sending 322 byte(s) to 172.16.110.201:3389
```

### Future Development

The following are several features that may be added in the future.

|                 Feature                  |                                                       Description                                                       |
|:----------------------------------------:|:-----------------------------------------------------------------------------------------------------------------------:|
| ~~Messenger Client HTTP Auto Reconnect~~ |                 ~~When a HTTP Messenger Client disconnects it'll attempt an auto-reconnect procedure.~~                 |
|    Messenger Client WS Auto Reconnect    |                   When a HTTP Messenger Client disconnects it'll attempt an auto-reconnect procedure.                   |
|       Proxychains Auto Generation        | When a new Messenger Client connects, generate a new proxychains configuration file in an operator-specified directory. |   
|   ~~Messenger Client Port Forwarding~~   |                      ~~Refactor the Messenger Client to handle local and remote port forwards.~~~                       |
|        Messenger Server Profiles         |                  Create profile to mimic the traffic of common web services such as SocketIO and AWS.                   |
|            ~~AES Encryption~~            |                                   ~~Add AES Encryption to both WebSockets and HTTP.~~                                   |
|         Verbose Messengers Table         |                  The messengers command should show the useragent and IP address as a verbose option.                   |

### Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)