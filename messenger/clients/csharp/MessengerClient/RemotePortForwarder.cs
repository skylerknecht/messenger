using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;

namespace MessengerClient
{
    public class RemotePortForwarder
    {
        private readonly MessengerClient _messenger;
        private readonly string _listeningHost;
        private readonly int _listeningPort;
        private readonly string _destinationHost;
        private readonly int _destinationPort;

        private TcpListener _tcpListener;

        public string Name { get; private set; }

        public RemotePortForwarder(MessengerClient messenger, string config)
        {
            _messenger = messenger;
            (_listeningHost, _listeningPort, _destinationHost, _destinationPort) = ParseConfig(config);
            Name = "Remote Port Forwarder";
        }

        /// <summary>
        /// Starts the port forwarder.
        /// </summary>
        public async Task StartAsync()
        {
            try
            {
                _tcpListener = new TcpListener(IPAddress.Parse(_listeningHost), _listeningPort);
                _tcpListener.Start();
                Console.WriteLine($"{Name} {GetHashCode()} is listening on {_listeningHost}:{_listeningPort}");

                while (true)
                {
                    var client = await _tcpListener.AcceptTcpClientAsync();
                    _ = HandleClientAsync(client); // Fire-and-forget to handle multiple clients concurrently.
                }
            }
            catch (SocketException ex)
            {
                Console.WriteLine($"{_listeningHost}:{_listeningPort} is already in use or encountered an error: {ex.Message}");
            }
        }

        /// <summary>
        /// Handles an incoming client connection.
        /// </summary>
        /// <param name="client">The connected TCP client.</param>
        private async Task HandleClientAsync(TcpClient client)
        {
            var clientId = Guid.NewGuid().ToString();

            var downstreamMessage = new InitiateForwarderClientReq(
                clientId,
                _destinationHost,
                _destinationPort
            );

            // Send the downstream message to the messenger.
            await _messenger.SendDownstreamMessageAsync(downstreamMessage);

            // Register the forwarder client.
            _messenger.ForwarderClients[clientId] = client;
        }

        /// <summary>
        /// Parses the configuration string to extract the host and port information.
        /// </summary>
        /// <param name="config">The configuration string.</param>
        /// <returns>A tuple containing the parsed host and port values.</returns>
        private (string listeningHost, int listeningPort, string destinationHost, int destinationPort) ParseConfig(string config)
        {
            var parts = config.Split(':');
            if (parts.Length != 4)
                throw new ArgumentException("Invalid config format. Expected format: listeningHost:listeningPort:destinationHost:destinationPort");

            return (parts[0], int.Parse(parts[1]), parts[2], int.Parse(parts[3]));
        }
    }
}
