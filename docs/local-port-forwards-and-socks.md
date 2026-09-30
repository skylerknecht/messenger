# SOCKS Proxy and Local Port Forwards

## SOCKS Proxy

The most common use-case for Messenger is setting up an ingress SOCKS proxy, allowing network traffic from external tools to be tunneled into a target network.

1. After a new messenger checks in, interact with it by entering the messenger ID:
```
[+] WebSocket Messenger `PWnauryxxD` is now connected.
(messenger)~# PWnauryxxD
(PWnauryxxD)~#
```

2. Use the `socks` command with a port (or host:port) to open a SOCKS proxy:
```
(PWnauryxxD)~# socks 1080
[*] Messenger `PWnauryxxD` is attempting to start SOCKS Server (127.0.0.1:1080 -> *:*).
[+] Messenger `PWnauryxxD` started SOCKS Server (127.0.0.1:1080 -> *:*).
```

To bind to a specific interface:
```
(PWnauryxxD)~# socks 0.0.0.0:1080
```

3. Use a proxy-capable tool or a proxifier like `proxychains` to send TCP traffic through the SOCKS proxy. An example `proxychains` config:
```
[ProxyList]
socks5  127.0.0.1 1080
```

4. Verify the tunnel is working:
```
$ proxychains curl ifconfig.io
[proxychains] Strict chain  ...  127.0.0.1:1080  ...  ifconfig.io:80  ...  OK
68.12.211.24
```

## Local Port Forward

Local port forwards tunnel traffic to a specific destination, unlike SOCKS which allows any destination.

1. Use the `local` command with `listening_host:listening_port:destination_host:destination_port`:
```
(PWnauryxxD)~# local 127.0.0.1:8089:10.0.0.5:80
[*] Messenger `PWnauryxxD` is attempting to start Local Port Forwarder (127.0.0.1:8089 -> 10.0.0.5:80).
[+] Messenger `PWnauryxxD` started Local Port Forwarder (127.0.0.1:8089 -> 10.0.0.5:80).
```

2. Traffic to `localhost:8089` is now forwarded through the messenger to `10.0.0.5:80` on the target network:
```
$ curl http://localhost:8089 -H "Host: 10.0.0.5"
```

IPv6 addresses must be wrapped in brackets:
```
(PWnauryxxD)~# local [::1]:8089:[::1]:80
```

## Port Scanning

Messenger supports port scanning through the SOCKS proxy or via the built-in `portscan` command.

### Built-in Scanner

The `portscan` command runs scans through the messenger directly:
```
(PWnauryxxD)~# portscan 10.0.0.0/24 --top-ports 100 --concurrency 50
```

View results with `scans`:
```
(PWnauryxxD)~# scans
```

### External Tools via SOCKS

For `nmap` through proxychains, note these caveats:
- Use `-sT` (full TCP connect scans) since SOCKS cannot handle raw sockets
- Use `-Pn` to skip host discovery
- Reduce timeouts in `proxychains.conf`:

```
dynamic_chain
proxy_dns
tcp_connect_time_out 3000
tcp_read_time_out 5000

[ProxyList]
socks5  127.0.0.1 1080
```

```
$ proxychains nmap -sT -Pn -p445 10.0.0.0/24
```

## Managing Forwarders

View active forwarders with the `forwarders` command:
```
(messenger)~# forwarders
                                    Forwarders
  Messenger     Type        Name    Clients     Listen        Destination
----------- ------------ --------- --------- ------------- ---------------
 PWnauryxxD  SOCKS Server AbCdEfGh     3     127.0.0.1:1080    *:*
```

Stop a forwarder by its name:
```
(messenger)~# stop AbCdEfGh
[*] Removed `AbCdEfGh` from forwarders.
```
