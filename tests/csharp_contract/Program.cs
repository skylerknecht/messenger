using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

sealed class RecordingClient : MessengerClient.MessengerClient
{
    public readonly List<object> Sent = new List<object>();
    public override Task ConnectAsync() => Task.CompletedTask;
    public override Task StartAsync() => Task.CompletedTask;
    public override Task SendUpstreamMessageAsync(object message)
    {
        Sent.Add(message);
        return Task.CompletedTask;
    }
    public override void CloseTransport() { }
}

static class Contract
{
    static int Passed;

    static void Check(string name, Action body)
    {
        body();
        Passed++;
        Console.WriteLine($"PASS {name}");
    }

    static void Assert(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    static T Throws<T>(Action body) where T : Exception
    {
        try { body(); }
        catch (T error) { return error; }
        throw new Exception($"Expected {typeof(T).Name}");
    }

    public static int Main()
    {
        byte[] key = MessengerClient.Crypto.Hash("contract-key");

        Check("SHA-256 key derivation", () => Assert(key.Length == 32, "key must be 32 bytes"));
        Check("AES-CBC random IV and round trip", () =>
        {
            byte[] plain = Enumerable.Range(0, 97).Select(i => (byte)i).ToArray();
            byte[] first = MessengerClient.Crypto.Encrypt(key, plain);
            byte[] second = MessengerClient.Crypto.Encrypt(key, plain);
            Assert(!first.SequenceEqual(second), "ciphertexts reused an IV");
            Assert(MessengerClient.Crypto.Decrypt(key, first).SequenceEqual(plain), "decrypt mismatch");
        });

        Check("all wire message types and concatenated order", () =>
        {
            object[] messages = {
                new InitiateTCPClientReq("tcp-req", "example.test", 443, "::1", 9000),
                new InitiateTCPClientRep("tcp-rep", "::1", 1234, 4, 0, "2001:db8::1", 5678),
                new SendDataMessage("tcp-data", new byte[] { 0, 1, 2, 255 }),
                new CheckInMessage("abcdefghij"),
                new InitiateBINDReq("bind-req", "::1", 4444, "host.test", 5555),
                new InitiateBINDRep("bind-rep", "127.0.0.1", 6666, 0),
            };
            byte[] wire = MessengerClient.MessengerClient.SerializeMessages(key, messages);
            // Append a raw CheckOutMessage frame (server-to-client only, not serializable by the client).
            byte[] checkoutFrame = new byte[] { 0, 0, 0, 7, 0, 0, 0, 8 };
            byte[] combined = new byte[wire.Length + checkoutFrame.Length];
            Buffer.BlockCopy(wire, 0, combined, 0, wire.Length);
            Buffer.BlockCopy(checkoutFrame, 0, combined, wire.Length, checkoutFrame.Length);
            List<object> parsed = MessengerClient.MessengerClient.DeserializeMessages(key, combined);
            object[] expected = messages.Append(new CheckOutMessage()).ToArray();
            Assert(parsed.Select(x => x.GetType()).SequenceEqual(expected.Select(x => x.GetType())), "type/order mismatch");
            var req = (InitiateTCPClientReq)parsed[0];
            Assert(req.ListeningHost == "::1" && req.ListeningPort == 9000, "optional RPF endpoint mismatch");
            Assert(((SendDataMessage)parsed[2]).Data.SequenceEqual(new byte[] { 0, 1, 2, 255 }), "binary data mismatch");
        });

        Check("incomplete and invalid frames", () =>
        {
            byte[] complete = MessageBuilder.SerializeMessage(key, new SendDataMessage("id", new byte[] { 1, 2, 3 }));
            byte[] incomplete = complete.Take(complete.Length - 1).ToArray();
            Assert(MessengerClient.MessengerClient.DeserializeMessages(key, incomplete).Count == 0, "incomplete frame was dispatched");
            Throws<ArgumentException>(() => MessageParser.DeserializeMessage(key, new byte[] { 0,0,0,7, 0,0,0,7 }));
        });

        Check("invalid ciphertext is a distinct decryption failure", () =>
        {
            // Type=SendData, total length=25, payload=17 bytes. AES-CBC cannot
            // decrypt a one-byte ciphertext after the 16-byte IV.
            byte[] wire = new byte[25];
            wire[3] = 3;
            wire[7] = 25;
            Throws<DecryptionException>(() => MessengerClient.MessengerClient.DeserializeMessages(key, wire));
        });

        Check("secure identifiers have required shape", () =>
        {
            var ids = Enumerable.Range(0, 1000)
                .Select(_ => MessengerClient.MessengerClient.AlphanumericIdentifier())
                .ToArray();
            Assert(ids.All(id => id.Length == 10 && id.All(char.IsLetterOrDigit)), "invalid identifier shape");
            Assert(ids.Distinct().Count() == ids.Length, "identifier collision in sample");
        });

        Check("checkout is terminal client state", () =>
        {
            var client = new RecordingClient();
            client.DispatchMessage(new CheckOutMessage());
            Assert(client.Killed, "checkout did not set killed");
        });

        Console.WriteLine($"C# contract checks passed: {Passed}");
        return 0;
    }
}
