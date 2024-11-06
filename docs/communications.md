# Messenger Communications Protocol

This protocol defines the structure and requirements for message exchange between Messenger Clients and the Messenger Server. It includes details on different message types, their components, and field sizes.


### Terms

| Term             | Description                                                                                                                                                                                                                       |
|------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Messenger Client | A client that connects over a transport layer to the Messenger Server and delivers Messages.                                                                                                                                      |
| Messenger Server | A server that manages multiple Forwarders by accepting and parsing Messages from Messenger Clients.                                                                                                                               |
| Forwarder        | Manages multiple Forwarder Clients and sends data upstream and downstream as Messages.                                                                                                                                            |
| Forwarder Client | Represents the TCP socket used to write or receive data. It is essential for sending data to the correct Forwarder Client on both ends to successfully establish local and remote port forwards.                                  |
| Message          | A complete data blob sent to or received by the Messenger Client or Messenger Server. | 

---

## Message Structure

A `Message` is composed of multiple components and contains the necessary information for Messenger to operate correctly.

### General Structure

```
                       Message Structure

+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Message Type       (4 bytes)          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Message Length      (4 bytes)          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|                            Value                              |
|                        (variable length)                      |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **Message Type**: Specifies the type of message (4 bytes).
- **Message Length**: Indicates the total length of the message, including the header and the `Value` field (4 bytes).
- **Value**: Variable-length field containing the specific data for each message type.

Here is your corrected table with the typos fixed:

| **Name**                          | **Message Type** | **Description**                                                               |
|-----------------------------------|------------------|-------------------------------------------------------------------------------|
| Initiate Forwarder Client Req     | `0x01`           | Establishes a new Forwarder Client.                                           |
| Initiate Forwarder Client Rep     | `0x02`           | Results of attempting to establish a new Forwarder Client.                    |
| Send Data                         | `0x03`           | Writes data to a Forwarder Client.                                            |

---

## Value Structures

Each message type has a specific structure for its `Value` field. The following sections provide the layout and field sizes for each message type.

### Initiate Forwarder Client Req (Message Type `0x01`)

Used to establish a new Forwarder Client connection.

```
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Forwarder Client ID Length      (4 bytes)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Forwarder Client ID       (variable)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                 IP Address Length            (4 bytes)        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         IP Address           (variable)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            Port              (4 bytes)        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **Forwarder Client ID**: A variable-length string with a 4-byte length prefix specifying its size.
- **IP Address**: A variable-length string with a 4-byte length prefix specifying its size.
- **Port**: The port to bind the Forwarder Client (4 bytes).

### Initiate Forwarder Client Rep (Message Type `0x02`)

Indicates the status of a Forwarder Client.

```
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Forwarder Client ID Length      (4 bytes)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Forwarder Client ID       (variable)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                Bind Address Length           (4 bytes)        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Bind Address          (variable)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Bind Port            (4 bytes)        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Address Type          (4 bytes)        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Reason              (4 bytes)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **Forwarder Client ID**: A variable-length string with a 4-byte length prefix specifying its size.
- **Bind Address**: A variable-length string with a 4-byte length prefix specifying its size.
- **Bind Port**: The port the Forwarder Client is bound to (4 bytes).
- **Address Type**: Type of address (e.g., IPv4, IPv6) (4 bytes).
- **Reason**: Reason code indicating the connection status (4 bytes).

### Send Data (Message Type `0x03`)

Used to send data to a Forwarder Client. The `Data` field is base64 encoded for safe transmission.

```
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Forwarder Client ID Length      (4 bytes)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Forwarder Client ID       (variable)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|                             Data                              |
|                        (variable length)                      |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **Forwarder Client ID**: A variable-length string with a 4-byte length prefix specifying its size.
- **Data**: The data payload, base64 encoded for safe transmission (variable length).

### Check In (Message Type `0x04`)

The Check In message is used by a Messenger Client to identify itself to the Messenger Server with a unique Messenger ID.

```
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Messenger ID Length           (4 bytes)         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Messenger ID           (variable)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```