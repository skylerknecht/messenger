# Chaining Messenger Clients

Messenger does not have a native chaining mechanism, but remote port forwarding makes it possible to forward the server's listener through a client, allowing a second client to connect through the first.

```
+-----------+        +-----------+        +-----------+
| Messenger |        | Messenger |        | Messenger |
| Server    | <----- | Client A  | <----- | Client B  |
|           |        |           |        |           |
+-----------+        +-----------+        +-----------+
  (operator)          (network 1)          (network 2)
```

## Setup

1. Connect Client A to the server and set up a remote port forward that exposes the server's listener on Client A's host:

```
[+] WebSocket Messenger `LDbNqWdgsk` is now connected.
(messenger)~# LDbNqWdgsk
(LDbNqWdgsk)~# remote 0.0.0.0:8888:127.0.0.1:8080
[*] Queued Remote Port Forwarder request for Messenger `LDbNqWdgsk` for (0.0.0.0:8888) -> (127.0.0.1:8080).
[+] Messenger `LDbNqWdgsk` is now remote forwarding (0.0.0.0:8888) -> (127.0.0.1:8080).
```

This means Client A is now listening on port 8888, and any connections to it are forwarded back to the server on port 8080.

2. Connect Client B to Client A's forwarded listener:

```
> client.py --server-url 192.168.1.20:8888 --encryption-key MyKey
[+] Connected to ws://192.168.1.20:8888/
```

3. Client B shows up as a new messenger on the server and can be used normally:

```
[+] WebSocket Messenger `SiHSttBrWG` is now connected.
(messenger)~# messengers
                                          Messengers
    Name     Transport   Status      IPs      Forwarders / Scanners   Sent      Received
  --------- ---------- ---------- ---------- ----------------------- -------- -----------
  LDbNqWdgsk WebSocket  connected  10.0.0.5        vHcsbeQnWM        4.57 KB   22.48 KB
  SiHSttBrWG WebSocket  connected  10.0.0.5            •••             0 B       0 B
```

Note that Client B's IP will appear as Client A's IP since the traffic is relayed through Client A.

## Multi-Hop Chains

This pattern extends to any depth. To add a third hop, set up a remote forward on Client B that points back to Client A's forwarded port, then connect Client C to Client B's listener.

Each hop adds latency, so keep chains short when possible.
