# Messenger

Messenger uses a client-server architecture to establish one or more SOCKS5 proxies to allow operators to interact with the local network the client is connected to. 
Two clients exist in Python and C# for cross-platform deployment. The clients use either WebSockets or HTTP to communicate with the server depending on which one is available. 
The server and clients are written in an asynchronous model to support large bandwidths such as network scanning. There are three primary use cases of Messenger. 
These include, within a C2 that supports execute-assembly but not SOCKS5, a C2 that only supports synchronous HTTP SOCKS5, or within an environment where HTTP 
must be used since the environment’s proxy does not support WebSockets. 

### Example Usage
The following example demonstrates the basic usage of running a Messenger Server and then connecting two Messenger Clients to the server. 

```
skyler.knecht@debian~# python3 messenger.py  

 __  __                                    
|  \/  | ___  ___ ___  ___ _ __   __ _  ___ _ __ 
| |\/| |/ _ \/ __/ __|/ _ \ '_ \ / _` |/ _ \ '__|
| |  | |  __/\__ \__ \  __/ | | | (_| |  __/ |   
|_|  |_|\___||___/___/\___|_| |_|\__, |\___|_|   
   by Skyler Knecht              |___/ v0.0.0

Welcome to the Messenger CLI, type exit or socks.
Messenger Server is running on wss://172.16.100.2:1337/
(messenger)~#
Socks Server (HTTP) on port 9050 has stopped
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
skyler.knecht@debian~# python3 examples/client.py https://172.16.100.2:1337
[+] Successfully connected to https://172.16.100.2:1337/socketio/?EIO=4&transport=polling
```

```
skyler.knecht@debian~# python3 examples/client.py wss://172.16.100.2:1337
[+] Successfully connected to wss://172.16.100.2:1337/socketio/?EIO=4&transport=websocket
```

### Messenger Client Arguments

Messenger client expects on argument to be provided, the URI to connect to. By default, if no protocol is provided Messenger Client will attempt the following protocols in order, ws, http, wss 
and https. 

```
skyler.knecht@debian~# python3 examples/client.py 172.16.100.2:1337
[!] Failed to connect to ws://172.16.100.2:1337/
[!] Failed to connect to http://172.16.100.2:1337/
[+] Successfully connected to wss://172.16.100.2:1337/socketio/?EIO=4&transport=websocket
```

Alternatively, The operator can specify a single protocol to attempt as in example usage or, a list of protocols to attempt 
by using `+` as a delimiter. 

```
skyler.knecht@debian~# python3 examples/client.py ws+http+http+http+wss+https://172.16.100.2:1337
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
socks5 127.0.0.1 9521
```

### Future Development

Currently, we're looking into several features to add. Please feel free to open a PR or issue request if anything comes up.

|                Feature                |                                                       Description                                                       |
|:-------------------------------------:|:-----------------------------------------------------------------------------------------------------------------------:|
|            Auto Reconnect             |                       Currently, if the Messenger Server stops, all Messenger Clients disconnect.                       |
|      Proxychains Auto Generation      | When a new Messenger Client connects, generate a new proxychains configuration file in an operator-specified directory. |   
| Messenger Client Port Forward Tasking |      Refactor the Messenger Client to connect and wait for incoming tasks to create local and remote port forwards.      |

### Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)