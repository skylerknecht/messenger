using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using System.Threading.Tasks;

namespace MessengerClient
{
    public class Program
    {
        // Constants for HTTP and WebSocket routes and user agent
        private const string HTTP_ROUTE = "socketio/?EIO=4&transport=polling";
        private const string WS_ROUTE = "socketio/?EIO=4&transport=websocket";
        private const string USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0";

        public static async Task Main(string[] args)
        {
            ServicePointManager.ServerCertificateValidationCallback = new RemoteCertificateValidationCallback(ValidateServerCertificate);

            if (args.Length < 1)
            {
                Console.WriteLine("Usage: Program <URL> <Encryption_Key> [remote_port_forwards...] [--proxy <proxy_config>]");
                return;
            }

            string uri = args[0];
            byte[] encryption_key = Crypto.Hash(args[1]);

            // Handling remotePortForwards and proxyConfig
            List<string> remotePortForwards = new List<string>();
            string proxyConfig = null;

            for (int i = 2; i < args.Length; i++)
            {
                if (args[i] == "--proxy" && i + 1 < args.Length)
                {
                    proxyConfig = args[i + 1];
                    i++;
                }
                else
                {
                    remotePortForwards.Add(args[i]);
                }
            }

            IWebProxy proxy = null;
            if (!string.IsNullOrEmpty(proxyConfig))
            {
                proxy = CreateWebProxy(proxyConfig);
                Console.WriteLine($"Using proxy: {proxyConfig}");
            }

            string[] attempts;

            uri = uri.Trim('/');

            if (uri.Contains("://"))
            {
                string[] urlParts = uri.Split(new[] { "://" }, 2, StringSplitOptions.None);
                attempts = urlParts[0].Split('+');
                uri = urlParts[1];
            }
            else
            {
                attempts = new[] { "ws", "http", "wss", "https" };
            }

            foreach (string attempt in attempts)
            {
                if (attempt.Contains("http"))
                {
                    bool success = await TryHttp($"{attempt}://{uri}/{HTTP_ROUTE}", encryption_key, remotePortForwards, proxy);
                    if (success)
                    {
                        await Task.Delay(-1);
                        return;
                    }
                }
                else if (attempt.Contains("ws"))
                {
                    bool success = await TryWs($"{attempt}://{uri}/{WS_ROUTE}", encryption_key, remotePortForwards, proxy);
                    if (success)
                    {
                        await Task.Delay(-1);
                        return;
                    }
                }
            }

            Console.WriteLine("All connection attempts failed.");
        }

        private static async Task<bool> TryHttp(string url, byte[] encryptionKey, List<string> remotePortForwards, IWebProxy proxy)
        {
            try
            {
                Console.WriteLine($"[HTTP] Trying {url}");
                var httpMessengerClient = new HTTPMessengerClient(url, encryptionKey, proxy);
                _ = httpMessengerClient.ConnectAsync();
                StartRemotePortForwardsAsync(httpMessengerClient, remotePortForwards);
                return true;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[HTTP] Failed to connect to {url}: {ex}");
                return false;
            }
        }

        private static async Task<bool> TryWs(string url, byte[] encryptionKey, List<string> remotePortForwards, IWebProxy proxy)
        {
            try
            {
                Console.WriteLine($"[WebSocket] Trying {url}");

                var webSocketMessengerClient = new WebSocketMessengerClient(url, encryptionKey, proxy);
                _ = webSocketMessengerClient.ConnectAsync();
                StartRemotePortForwardsAsync(webSocketMessengerClient, remotePortForwards);
                return true;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[WebSocket] Failed to connect to {url}: {ex}");
                return false;
            }
        }

        private static IWebProxy CreateWebProxy(string proxyConfig)
        {
            var proxyUri = new Uri(proxyConfig);
            var webProxy = new WebProxy(proxyUri);

            // Check if the proxy URI contains credentials
            if (!string.IsNullOrEmpty(proxyUri.UserInfo))
            {
                string[] userInfo = proxyUri.UserInfo.Split(':');
                if (userInfo.Length == 2)
                {
                    webProxy.Credentials = new NetworkCredential(userInfo[0], userInfo[1]);
                }
            }

            return webProxy;
        }

        private static async Task StartRemotePortForwardsAsync(MessengerClient messengerClient, List<string> remotePortForwards)
        {
            foreach (var config in remotePortForwards)
            {
                try
                {
                    var forwarder = new RemotePortForwarder(messengerClient, config);
                    _ = forwarder.StartAsync(); // Fire-and-forget to start each forwarder concurrently
                    Console.WriteLine($"Started RemotePortForwarder with config: {config}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Failed to start RemotePortForwarder with config {config}: {ex.Message}");
                }
            }
        }

        private static bool ValidateServerCertificate(object sender, X509Certificate certificate, X509Chain chain, SslPolicyErrors sslPolicyErrors)
        {
            return true; // Always accept
        }
    }
}
