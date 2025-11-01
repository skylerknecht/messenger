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