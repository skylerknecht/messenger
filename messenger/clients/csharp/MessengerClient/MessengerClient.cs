using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Threading.Tasks;

namespace MessengerClient
{
    public abstract class MessengerClient
    {
        // Stores active TcpClients with their unique identifiers
        public ConcurrentDictionary<string, TcpClient> ForwarderClients = new ConcurrentDictionary<string, TcpClient>();

        /// <summary>
        /// Establishes the connection to the server.
        /// </summary>
        public abstract Task ConnectAsync();

        /// <summary>
        /// Sends a downstream message to the server.
        /// 
        /// NOTE: This method's signature still takes a 'byte[]'.
        ///       So in code below, we create message objects,
        ///       then serialize them with MessageBuilder.SerializeMessage,
        ///       and *that* byte[] is what we pass here.
        /// </summary>
        public abstract Task SendDownstreamMessageAsync(object message);

        /// <summary>
        /// Handles an incoming message from the server (already parsed).
        /// </summary>
        /// <param name="message">A fully parsed message object.</param>
        public abstract Task HandleMessageAsync(object message);

        /// <summary>
        /// Plural version of DeserializeMessage. It will keep reading messages
        /// from the input <paramref name="rawData"/> until no bytes remain.
        /// </summary>
        /// <param name="encryptionKey">The encryption key used to decrypt messages.</param>
        /// <param name="rawData">The raw bytes that may contain multiple messages.</param>
        /// <returns>A list of parsed message objects.</returns>
        public static List<object> DeserializeMessages(byte[] encryptionKey, byte[] rawData)
        {
            var messages = new List<object>();
            byte[] leftover = rawData;

            // Keep deserializing until we've exhausted all data
            while (leftover.Length > 0)
            {
                // (byte[] leftover, object parsedMessage)
                var (newLeftover, parsedMessage) = MessageParser.DeserializeMessage(encryptionKey, leftover);
                messages.Add(parsedMessage);
                leftover = newLeftover;
            }

            return messages;
        }

        /// <summary>
        /// Plural version of SerializeMessage. Takes a list of message objects
        /// and concatenates each one into a single byte array.
        /// </summary>
        /// <param name="encryptionKey">The encryption key used for encryption.</param>
        /// <param name="messages">A collection of message objects to be serialized.</param>
        /// <returns>A single byte array containing all messages (one after another).</returns>
        public static byte[] SerializeMessages(byte[] encryptionKey, IEnumerable<object> messages)
        {
            MemoryStream ms = null;
            try
            {
                ms = new MemoryStream();
                foreach (var message in messages)
                {
                    byte[] singleMessageBytes = MessageBuilder.SerializeMessage(encryptionKey, message);
                    ms.Write(singleMessageBytes, 0, singleMessageBytes.Length);
                }
                return ms.ToArray();
            }
            finally
            {
                if (ms != null)
                    ms.Dispose();
            }
        }

        /// <summary>
        /// Handles a request to initiate a forwarder client.
        /// </summary>
        /// <param name="message">The parsed request data.</param>
        public async Task HandleInitiateForwarderClientReqAsync(InitiateForwarderClientReq message)
        {
            try
            {
                var client = new TcpClient();
                // If IpAddress is a string like "127.0.0.1", this will do DNS resolution.
                await client.ConnectAsync(message.IpAddress, message.Port);

                Console.WriteLine("Connected forwarder client successfully.");
                ForwarderClients[message.ForwarderClientId] = client;

                // Extract local bind info
                string bindAddress = ((IPEndPoint)client.Client.LocalEndPoint).Address.ToString();
                int bindPort = ((IPEndPoint)client.Client.LocalEndPoint).Port;

                // Build an InitiateForwarderClientRep object (success)
                var repObj = new InitiateForwarderClientRep(
                    message.ForwarderClientId,
                    bindAddress,
                    bindPort,
                    0,  // addressType
                    0   // reason = 0 => success
                );

                // Serialize and send downstream
                await SendDownstreamMessageAsync(repObj);

                // Start streaming for this forwarder client
                _ = StreamAsync(message.ForwarderClientId);
            }
            catch (Exception)
            {
                // Build an InitiateForwarderClientRep object (failure)
                var repObj = new InitiateForwarderClientRep(
                    message.ForwarderClientId,
                    string.Empty,
                    0,
                    0,
                    1 // reason = 1 => fail
                );

                await SendDownstreamMessageAsync(repObj);
            }
        }

        /// <summary>
        /// Streams data from a forwarder client to the server.
        /// </summary>
        /// <param name="forwarderClientId">Unique identifier for the forwarder client.</param>
        protected async Task StreamAsync(string forwarderClientId)
        {
            if (!ForwarderClients.TryGetValue(forwarderClientId, out TcpClient client))
                return;

            NetworkStream stream = null;

            try
            {
                stream = client.GetStream();
                var buffer = new byte[4096];
                int bytesRead;

                while ((bytesRead = await stream.ReadAsync(buffer, 0, buffer.Length)) > 0)
                {
                    // Copy out exactly 'bytesRead' worth of data
                    var dataToSend = new byte[bytesRead];
                    Array.Copy(buffer, 0, dataToSend, 0, bytesRead);

                    // Build a SendDataMessage object
                    var sdmObj = new SendDataMessage(forwarderClientId, dataToSend);

                    // Send downstream
                    await SendDownstreamMessageAsync(sdmObj);
                }
            }
            catch
            {
                // Handle disconnection or stream errors
            }
            finally
            {
                stream?.Dispose();

                // Remove from dictionary
                ForwarderClients.TryRemove(forwarderClientId, out _);

                // Notify the server about client disconnection
                var closeObj = new SendDataMessage(forwarderClientId, Array.Empty<byte>());
                await SendDownstreamMessageAsync(closeObj);
            }
        }
    }
}