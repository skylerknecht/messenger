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

### Local Port Forward

Similar to SOCKS proxies, Local Port Forwards also allow network traffic from external tools to be tunneled to a target network. However, instead of any detination
local port forwards have a specific destination.

1. Use the `local` command to specify a listening ip and port along with a destination ip and port.
```
(UkKPRJYtZk)~# local localhost:8089:google.com:80
[*] Attempting to forward (localhost:8089) -> (google.com:80).
[+] Messenger `UkKPRJYtZk` now forwarding (localhost:8089) -> (google.com:80).
(UkKPRJYtZk)~#
```

2. Make a GET request to google by hitting our localhost on port 8089.

```
$ curl http://localhost:8089 -H "host:google.com"
<HTML><HEAD><meta http-equiv="content-type" content="text/html;charset=utf-8">
<TITLE>301 Moved</TITLE></HEAD><BODY>
<H1>301 Moved</H1>
The document has moved
<A HREF="http://www.google.com/">here</A>.
</BODY></HTML>
```