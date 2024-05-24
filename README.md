# Messenger

Messenger uses a client-server architecture to establish one or more SOCKS5 proxies to allow operators to interact with the local network the client is connected to. 
Two clients exist in Python and C# for cross-platform deployment. The clients use either WebSockets or HTTP to communicate with the server depending on which one is available. 
The server and clients are written in an asynchronous model to support large bandwidths such as network scanning. There are three primary use cases of Messenger. 
These include, within a C2 that supports execute-assembly but not SOCKS5, a C2 that only supports synchronous HTTP SOCKS5, or within an environment where HTTP 
must be used since the environment’s proxy does not support WebSockets. 

### Installation

Messenger comes with a setup.py configured for pipx. Alternativelly, using `pip` to install the requirements.txt file will also work.

```
skyler.knecht@debian~# pipx install git+https://github.com/skylerknecht/messenger 
installed package messenger 0.1.1, installed using Python 3.12.3
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

Welcome to the Messenger CLI, type exit or socks.
Messenger Server is running on http+ws://127.0.0.1:1337/
(messenger)~# 
```

### Example Usage
The following example demonstrates the basic usage of running a Messenger Server and then connecting two Messenger Clients to the server. 

```
skyler.knecht@debian~# messenger-server --quiet
Welcome to the Messenger CLI, type exit or socks.
Messenger Server is running on http+ws://172.16.100.2:1337/
(messenger)~#
Socks Server (HTTP) on port 9050 has started
Socks Server (WS) on port 9051 has started
(messenger)~# socks
            SOCKS SERVERS             
transport   port   client(s) listening
--------- -------- --------- ---------
  HTTP      9050       0       True  
   WS       9051       0       True  
(messenger)~#
```

```
skyler.knecht@debian~# messenger-client http://172.16.100.2:1337
[+] Successfully connected to http://172.16.100.2:1337/socketio/?EIO=4&transport=polling
```

```
skyler.knecht@debian~# messenger-client ws://172.16.100.2:1337
[+] Successfully connected to ws://172.16.100.2:1337/socketio/?EIO=4&transport=websocket
```

### Messenger Client Arguments

Messenger Client requires the Messenger Server's URI. This argument can be of many formats, depending on the protool the Messenger Server
is listening on. By default, if no protocol is provided Messenger Client will attempt ws, http, wss and https. Once successful, no further
attempts will be made. 

```
skyler.knecht@debian~# messenger-client 172.16.100.2:1337
[!] Failed to connect to ws://172.16.100.2:1337/
[!] Failed to connect to http://172.16.100.2:1337/
[+] Successfully connected to wss://172.16.100.2:1337/socketio/?EIO=4&transport=websocket
```

Alternatively, the operator can specify one or more protocols, delimited by `+`, to make connection attempts with. 

```
skyler.knecht@debian~# messenger-client ws+http+http+http+wss+https://172.16.100.2:1337
[!] Failed to connect to ws://172.16.100.2:1337/
[!] Failed to connect to http://172.16.100.2:1337/
[!] Failed to connect to http://172.16.100.2:1337/
[!] Failed to connect to http://172.16.100.2:1337/
[+] Successfully connected to wss://172.16.100.2:1337/socketio/?EIO=4&transport=websocket
```

### Messenger Client (C#)

The Messenger Client exists in Python and C#. The C# version lives on a separate GitHub [repo](https://github.com/skylerknecht/messenger-client). 
All the same arguments as discussed above apply. The client is written in .NET Framework and uses dnMerge to statically compile all it's depencides.  

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

### Future Development

The following are several features that may be added in the future.

|                Feature                |                                                       Description                                                       |
|:-------------------------------------:|:-----------------------------------------------------------------------------------------------------------------------:|
|    Messenger Client Auto Reconnect    |                     When a Messenger Client disconnects it'll attempt an auto-reconnect procedure.                      |
|      Proxychains Auto Generation      | When a new Messenger Client connects, generate a new proxychains configuration file in an operator-specified directory. |   
| Messenger Client Port Forward Tasking |     Refactor the Messenger Client to connect and wait for incoming tasks to create local and remote port forwards.      |
|       Messenger Server Profiles       |                  Create profile to mimic the traffic of common web services such as SocketIO and AWS.                   |

### Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)