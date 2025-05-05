# Messenger Client

This repository is hosting the client meant to be used with the [Messenger Server](https://github.com/skylerknecht/messenger). 
The seperation is meant to seperate issues with the Messenger Server and Messenger Client. Please open any issues with the Messenger Client here. 
All example usage and additional information can be found on Messenger Server. 

```
+-----------+        +-----------+                            +-----------+        +-----------+
| SOCKS     |        | Messenger |   Egress (Over Internet)   | Messenger |        | Remote    |
| Client    | -----> | Server    | <------------------------- | Client    | -----> | Resource  |
|           |        |           |     (HTTP/Web Sockets)     |           |        |           |
+-----------+        +-----------+                            +-----------+        +-----------+ 
```


### Egress Protocols:
Connect Messenger client to a Messenger server using one of four (4) currently supported protocols:

| Protocol          | Abbreviation  |
| ----------------- | ------------- |
| Web Socket        | ws://         |
| Web Socket Secure | wss://        |
| HTTP Polling      | http://       |
| HTTPS Polling     | https://      |

### Command Line Usage:
```
# Connect the Messenger Client to example.com on port 80. Try all available protocols, starting with Web Socket, then HTTP, then Web Socket Secure, then HTTPS.
MessengerClient.exe example.com

# Connect the Messenger Client to example.com on port 8080 with Web Sockets first and fall back to HTTP, then HTTPS if each transport fails.
MessengerClient.exe ws+http+https://example.com:8080

# Connect the Messenger Client to example.com on port 443 using HTTPS only
MessengerClient.exe https://example.com
```

### Credits 

- Skyler Knecht (@SkylerKnecht)
- Kevin Clark (@GuhnooPlusLinux)
