using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace MessengerClient
{
    public class WebSocketMessengerClient : MessengerClient
    {
        private readonly Uri _uri;
        private readonly byte[] _encryptionKey;
        private readonly IWebProxy _proxy; // Added proxy parameter
        private ClientWebSocket _webSocket;
        private readonly ConcurrentQueue<object> _downstreamMessages;
        private string _messengerId;
        private CancellationTokenSource _cancellationTokenSource = new CancellationTokenSource();

        public WebSocketMessengerClient(string uri, byte[] encryptionKey, IWebProxy proxy = null)
        {
            _uri = new Uri(uri);
            _encryptionKey = encryptionKey;
            _proxy = proxy; // Assign proxy
            _webSocket = new ClientWebSocket();
            _downstreamMessages = new ConcurrentQueue<object>();
            _messengerId = String.Empty;

            // Apply proxy if provided
            if (_proxy != null)
            {
                _webSocket.Options.Proxy = _proxy;
            }
        }

        /// <summary>
        /// Establishes a WebSocket connection to the server.
        /// </summary>
        public override async Task ConnectAsync()
        {
            try
            {
                Console.WriteLine("Connecting to WebSocket server...");
                await _webSocket.ConnectAsync(_uri, CancellationToken.None);
                Console.WriteLine("Connected!");

                // Start receiving and sending tasks
                var receivingTask = ReceiveMessagesAsync();
                var sendingTask = SendMessages(_cancellationTokenSource.Token);
                await Task.WhenAll(receivingTask, sendingTask);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error connecting to WebSocket server: {ex.Message}");
            }
        }

        /// <summary>
        /// Receives messages from the WebSocket server.
        /// </summary>
        private async Task ReceiveMessagesAsync()
        {
            var buffer = new byte[4096];
            var messageBuffer = new MemoryStream(); // To accumulate fragmented messages

            while (_webSocket.State == WebSocketState.Open)
            {
                try
                {
                    var result = await _webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), CancellationToken.None);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        Console.WriteLine("WebSocket connection closed.");
                        break;
                    }

                    messageBuffer.Write(buffer, 0, result.Count);

                    if (result.EndOfMessage)
                    {
                        // The entire message has been received
                        byte[] messageData = messageBuffer.ToArray();
                        messageBuffer.SetLength(0); // Reset buffer

                        //if (result.MessageType == WebSocketMessageType.Binary)
                        //{
                        try
                        {
                            var messages = DeserializeMessages(_encryptionKey, messageData);

                                foreach (var message in messages)
                                {
                                    await HandleMessageAsync(message); // Pass the parsed message here
                                }
                            }
                            catch (Exception ex)
                            {
                                Console.WriteLine($"Error parsing message: {ex.Message}");
                            }
                        //}
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Error receiving message: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// Handles incoming messages based on their type.
        /// </summary>
        /// <param name="message">The parsed message.</param>
        public override async Task HandleMessageAsync(object message)
        {
            switch (message)
            {
                case InitiateForwarderClientReq reqMessage:
                    await HandleInitiateForwarderClientReqAsync(reqMessage);
                    break;

                case InitiateForwarderClientRep repMessage:
                    _ = StreamAsync(repMessage.ForwarderClientId);
                    break;

                case SendDataMessage sendDataMessage:
                    if (ForwarderClients.TryGetValue(sendDataMessage.ForwarderClientId, out var client))
                    {
                        await client.GetStream().WriteAsync(sendDataMessage.Data, 0, sendDataMessage.Data.Length);
                    }
                    break;

                case CheckInMessage checkInMessage:
                    _messengerId = checkInMessage.MessengerId;
                    break;

                default:
                    Console.WriteLine("Unknown message type received");
                    break;
            }
        }

        /// <summary>
        /// Sends a downstream message to the WebSocket server.
        /// </summary>
        /// <param name="messageData">The byte array containing the message data.</param>
        public override async Task SendDownstreamMessageAsync(object message)
        {
            _downstreamMessages.Enqueue(message);
        }

        private async Task SendMessages(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                var downstreamMessages = new List<object>();

                // Always append a CheckInMessage first (if that's what you intend)
                CheckInMessage checkInMessage = new CheckInMessage(_messengerId);
                downstreamMessages.Add(checkInMessage);

                // Then dequeue and append each queued message
                while (_downstreamMessages.TryDequeue(out var message))
                {
                    downstreamMessages.Add(message);
                }

                ArraySegment<byte> content = new ArraySegment<byte>(SerializeMessages(_encryptionKey, downstreamMessages));
                await _webSocket.SendAsync(content, WebSocketMessageType.Binary, true, token);
                await Task.Delay(10);
            }
        }

        /// <summary>
        /// Closes the WebSocket connection.
        /// </summary>
        public async Task CloseAsync()
        {
            if (_webSocket.State == WebSocketState.Open)
            {
                await _webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Closing connection", CancellationToken.None);
                Console.WriteLine("WebSocket connection closed.");
            }
        }
    }
}
