using System;
using System.Linq;
using System.Text;
using System.Security.Cryptography;


// ----------------------------------------------------------------------
// 1. Message Classes (now using int instead of uint)
// ----------------------------------------------------------------------
public class CheckInMessage
{
    public string MessengerId { get; }
    public CheckInMessage(string messengerId)
    {
        MessengerId = messengerId;
    }
}

public class InitiateForwarderClientReq
{
    public string ForwarderClientId { get; }
    public string IpAddress { get; }
    public int Port { get; }

    public InitiateForwarderClientReq(string forwarderClientId, string ipAddress, int port)
    {
        ForwarderClientId = forwarderClientId;
        IpAddress = ipAddress;
        Port = port;
    }
}

public class InitiateForwarderClientRep
{
    public string ForwarderClientId { get; }
    public string BindAddress { get; }
    public int BindPort { get; }
    public int AddressType { get; }
    public int Reason { get; }

    public InitiateForwarderClientRep(
        string forwarderClientId,
        string bindAddress,
        int bindPort,
        int addressType,
        int reason)
    {
        ForwarderClientId = forwarderClientId;
        BindAddress = bindAddress;
        BindPort = bindPort;
        AddressType = addressType;
        Reason = reason;
    }
}

public class SendDataMessage
{
    public string ForwarderClientId { get; }
    public byte[] Data { get; }

    public SendDataMessage(string forwarderClientId, byte[] data)
    {
        ForwarderClientId = forwarderClientId;
        Data = data;
    }
}


// ----------------------------------------------------------------------
// 2. MessageParser: Reading/Decrypting Bytes
// ----------------------------------------------------------------------
public static class MessageParser
{
    /// <summary>
    /// Read the first 4 bytes of <paramref name="data"/> as a big-endian uint32.
    /// Returns (uintValue, leftoverBytes).
    /// </summary>
    public static (uint Value, byte[] Remainder) ReadUInt32(byte[] data)
    {
        if (data.Length < 4)
            throw new ArgumentException("Not enough bytes to read a 32-bit value.");

        // Big-endian decode into a uint
        uint value = (uint)((data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]);
        byte[] remainder = data.Skip(4).ToArray();

        return (value, remainder);
    }

    /// <summary>
    /// Reads a length-prefixed UTF-8 string:
    ///  1) read a uint32 length
    ///  2) read 'length' bytes
    ///  3) decode UTF-8
    /// Returns (stringValue, leftoverBytes).
    /// </summary>
    public static (string Value, byte[] Remainder) ReadString(byte[] data)
    {
        var (length, remainder) = ReadUInt32(data);
        if (remainder.Length < length)
            throw new ArgumentException($"Not enough bytes to read string of length {length}.");

        string s = Encoding.UTF8.GetString(remainder, 0, (int)length);
        byte[] leftover = remainder.Skip((int)length).ToArray();

        return (s, leftover);
    }

    /// <summary>
    /// Parses the payload of a 0x04 'CheckIn' message (no decryption).
    /// </summary>
    public static CheckInMessage ParseCheckIn(byte[] value)
    {
        var (messengerId, _) = ReadString(value);
        return new CheckInMessage(messengerId);
    }

    /// <summary>
    /// Parses the payload of a 0x01 'InitiateForwarderClientReq' message.
    /// </summary>
    public static InitiateForwarderClientReq ParseInitiateForwarderClientReq(byte[] value)
    {
        var (forwarderClientId, remainder) = ReadString(value);
        var (ipAddress, remainder2) = ReadString(remainder);
        var (port, remainder3) = ReadUInt32(remainder2);

        // cast uint -> int
        return new InitiateForwarderClientReq(
            forwarderClientId,
            ipAddress,
            (int)port
        );
    }

    /// <summary>
    /// Parses the payload of a 0x02 'InitiateForwarderClientRep' message.
    /// </summary>
    public static InitiateForwarderClientRep ParseInitiateForwarderClientRep(byte[] value)
    {
        var (forwarderClientId, remainder) = ReadString(value);
        var (bindAddress, remainder2) = ReadString(remainder);
        var (bindPort, remainder3) = ReadUInt32(remainder2);
        var (addressType, remainder4) = ReadUInt32(remainder3);
        var (reason, remainder5) = ReadUInt32(remainder4);

        // cast all uint -> int
        return new InitiateForwarderClientRep(
            forwarderClientId,
            bindAddress,
            (int)bindPort,
            (int)addressType,
            (int)reason
        );
    }

    /// <summary>
    /// Parses the payload of a 0x03 'SendDataMessage'.
    /// </summary>
    public static SendDataMessage ParseSendData(byte[] value)
    {
        var (forwarderClientId, remainder) = ReadString(value);
        var (encodedData, remainder2) = ReadString(remainder);

        byte[] rawData = Convert.FromBase64String(encodedData);
        return new SendDataMessage(
            forwarderClientId,
            rawData
        );
    }

    /// <summary>
    /// High-level parse entrypoint:
    ///   1) read the message_type (uint32)
    ///   2) read the message_length (uint32)
    ///   3) slice out the encrypted payload
    ///   4) decrypt or parse plaintext
    /// Returns (leftoverBytes, parsedMessage).
    /// </summary>
    public static (byte[] leftover, object parsedMessage) DeserializeMessage(
        byte[] encryptionKey,
        byte[] rawData)
    {
        // 1) Read the message type
        var (messageType, dataAfterType) = ReadUInt32(rawData);

        // 2) Read the total message length
        var (messageLength, dataAfterLength) = ReadUInt32(dataAfterType);

        // 3) Extract the (messageLength - 8) payload bytes
        int payloadLen = (int)messageLength - 8;
        if (dataAfterLength.Length < payloadLen)
            throw new ArgumentException("Not enough bytes in data for the payload.");

        byte[] payload = dataAfterLength.Take(payloadLen).ToArray();
        byte[] leftover = dataAfterLength.Skip(payloadLen).ToArray();

        // 4) Decrypt or parse plaintext, depending on message type
        object parsedMsg;
        switch (messageType)
        {
            case 0x01:
                {
                    byte[] decrypted = MessengerClient.Crypto.Decrypt(encryptionKey, payload);
                    parsedMsg = ParseInitiateForwarderClientReq(decrypted);
                    break;
                }
            case 0x02:
                {
                    byte[] decrypted = MessengerClient.Crypto.Decrypt(encryptionKey, payload);
                    parsedMsg = ParseInitiateForwarderClientRep(decrypted);
                    break;
                }
            case 0x03:
                {
                    byte[] decrypted = MessengerClient.Crypto.Decrypt(encryptionKey, payload);
                    parsedMsg = ParseSendData(decrypted);
                    break;
                }
            case 0x04:
                {
                    // According to the Python version, we do NOT decrypt for 0x04
                    parsedMsg = ParseCheckIn(payload);
                    break;
                }
            default:
                throw new ArgumentException($"Unknown message type: 0x{messageType:X}");
        }

        return (leftover, parsedMsg);
    }
}


// ----------------------------------------------------------------------
// 3. MessageBuilder: Creating/Encrypting Bytes
// ----------------------------------------------------------------------
public static class MessageBuilder
{
    /// <summary>
    /// Given a message object (one of our 4 types), build the fully formed
    /// byte array (header + possibly encrypted payload).
    /// </summary>
    public static byte[] SerializeMessage(byte[] encryptionKey, object msg)
    {
        byte[] payload;
        uint messageType;

        switch (msg)
        {
            case InitiateForwarderClientReq req:
                messageType = 0x01;
                payload = MessengerClient.Crypto.Encrypt(
                    encryptionKey,
                    BuildInitiateForwarderClientReq(
                        req.ForwarderClientId,
                        req.IpAddress,
                        req.Port
                    )
                );
                break;

            case InitiateForwarderClientRep rep:
                messageType = 0x02;
                payload = MessengerClient.Crypto.Encrypt(
                    encryptionKey,
                    BuildInitiateForwarderClientRep(
                        rep.ForwarderClientId,
                        rep.BindAddress,
                        rep.BindPort,
                        rep.AddressType,
                        rep.Reason
                    )
                );
                break;

            case SendDataMessage sdm:
                messageType = 0x03;
                payload = MessengerClient.Crypto.Encrypt(
                    encryptionKey,
                    BuildSendData(
                        sdm.ForwarderClientId,
                        sdm.Data
                    )
                );
                break;

            case CheckInMessage cim:
                messageType = 0x04;
                // The Python code does not encrypt CheckInMessage
                payload = BuildCheckInMessage(cim.MessengerId);
                break;

            default:
                throw new ArgumentException($"Unknown message type: {msg.GetType().Name}");
        }

        return BuildMessage(messageType, payload);
    }

    /// <summary>
    /// Packs [message_type, total_length, payload] together in big-endian format.
    /// </summary>
    public static byte[] BuildMessage(uint messageType, byte[] payload)
    {
        // total_length = 8 (header) + payload length
        uint messageLength = (uint)(8 + payload.Length);

        // Build the 8-byte header (all big-endian)
        byte[] header = new byte[8];
        WriteUInt32(header, 0, messageType);    // message_type
        WriteUInt32(header, 4, messageLength);  // total_length

        // Concatenate header + payload
        return Combine(header, payload);
    }

    /// <summary>
    /// Encodes a string with a 4-byte length prefix (big-endian), plus UTF-8 data.
    /// </summary>
    public static byte[] BuildString(string value)
    {
        byte[] encoded = Encoding.UTF8.GetBytes(value);
        byte[] lengthBytes = new byte[4];
        WriteUInt32(lengthBytes, 0, (uint)encoded.Length);

        return Combine(lengthBytes, encoded);
    }

    public static byte[] BuildCheckInMessage(string messengerId)
    {
        return BuildString(messengerId);
    }

    public static byte[] BuildInitiateForwarderClientReq(
        string forwarderClientId,
        string ipAddress,
        int port)
    {
        var part1 = BuildString(forwarderClientId);
        var part2 = BuildString(ipAddress);

        // We'll still write it as a uint on the wire
        byte[] part3 = new byte[4];
        WriteUInt32(part3, 0, (uint)port);

        return Combine(part1, part2, part3);
    }

    public static byte[] BuildInitiateForwarderClientRep(
        string forwarderClientId,
        string bindAddress,
        int bindPort,
        int addressType,
        int reason)
    {
        var part1 = BuildString(forwarderClientId);
        var part2 = BuildString(bindAddress);

        // Next 3 fields => 3*4 bytes => 12 bytes
        byte[] part3 = new byte[12];
        WriteUInt32(part3, 0, (uint)bindPort);
        WriteUInt32(part3, 4, (uint)addressType);
        WriteUInt32(part3, 8, (uint)reason);

        return Combine(part1, part2, part3);
    }

    public static byte[] BuildSendData(
        string forwarderClientId,
        byte[] data)
    {
        var part1 = BuildString(forwarderClientId);
        string encodedData = Convert.ToBase64String(data);
        var part2 = BuildString(encodedData);

        return Combine(part1, part2);
    }

    // ----------------------------------------------------------------------
    // Helper: Write a uint32 to a byte array in big-endian
    // ----------------------------------------------------------------------
    public static void WriteUInt32(byte[] buffer, int offset, uint value)
    {
        buffer[offset] = (byte)((value >> 24) & 0xFF);
        buffer[offset + 1] = (byte)((value >> 16) & 0xFF);
        buffer[offset + 2] = (byte)((value >> 8) & 0xFF);
        buffer[offset + 3] = (byte)(value & 0xFF);
    }

    // ----------------------------------------------------------------------
    // Helper: Concatenate multiple byte arrays
    // ----------------------------------------------------------------------
    public static byte[] Combine(params byte[][] arrays)
    {
        int totalLength = 0;
        foreach (var arr in arrays)
            totalLength += arr.Length;

        byte[] result = new byte[totalLength];
        int offset = 0;

        foreach (var arr in arrays)
        {
            Buffer.BlockCopy(arr, 0, result, offset, arr.Length);
            offset += arr.Length;
        }

        return result;
    }
}
