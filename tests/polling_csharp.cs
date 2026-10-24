// Compile beside a rendered HttpServiceClient.cs. HTTP is replaced by an in-memory handler.
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;

namespace ServiceClient
{
    // Record requested delays for deterministic backoff checks; otherwise use a real semaphore.
    public class SemaphoreSlim
    {
        private readonly System.Threading.SemaphoreSlim _inner;
        public static Action<int> ObserveWait;
        public SemaphoreSlim(int initial, int maximum) { _inner = new System.Threading.SemaphoreSlim(initial, maximum); }
        public bool Wait(int delay) { return _inner.Wait(delay); }
        public int Release() { return _inner.Release(); }
        public Task<bool> WaitAsync(int delay)
        {
            if (ObserveWait == null) return _inner.WaitAsync(delay);
            ObserveWait(delay);
            return Task.FromResult(false);
        }
    }

    public class CheckInMessage { public string MessengerId; public CheckInMessage(string id) { MessengerId = id; } }
    public class CheckOutMessage { }
    public static class MessageBuilder
    {
        public static byte[] SerializeMessage(byte[] key, object message) { return new byte[0]; }
    }

    public class ServiceClient
    {
        public bool Killed;
        public string Identifier = "test";
        public const int MaxBatchSize = 100;
        public static List<object> LastBatch;
        public virtual Task ConnectAsync() { return Task.CompletedTask; }
        public virtual Task StartAsync() { return Task.CompletedTask; }
        public virtual Task SendUpstreamMessageAsync(object message) { return Task.CompletedTask; }
        public virtual void CloseTransport() { }
        protected virtual void HandleCheckout() { Killed = true; }
        public void Stop() { HandleCheckout(); }
        protected Task ReadvertiseForwardersAsync() { return Task.CompletedTask; }
        protected void DispatchMessage(object message) { }
        protected static byte[] SerializeMessages(byte[] key, List<object> batch)
        {
            LastBatch = new List<object>(batch);
            return new byte[0];
        }
        protected static List<object> DeserializeMessages(byte[] key, byte[] data)
        {
            if (data.Length == 0) return new List<object>();
            return new List<object> { data[0] == 2 ? new object() : new CheckInMessage("test") };
        }
    }

    class PollingTest
    {
        class Handler : HttpMessageHandler
        {
            public int Requests;
            public bool SentActivity;
            protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
            {
                Requests++;
                if (Requests == 51) SentActivity = ServiceClient.LastBatch.Count == 2;
                var content = Requests == 51 ? new byte[0] : new byte[] { Requests == 52 ? (byte)2 : (byte)1 };
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(content) });
            }
        }

        static void Check(bool condition, string reason)
        {
            if (!condition) throw new Exception(reason);
        }

        static HttpServiceClient Create(Handler handler)
        {
            var client = new HttpServiceClient("http://localhost", new byte[32], "test");
            var field = typeof(HttpServiceClient).GetField("_httpClient", BindingFlags.Instance | BindingFlags.NonPublic);
            ((HttpClient)field.GetValue(client)).Dispose();
            field.SetValue(client, new HttpClient(handler));
            return client;
        }

        static async Task Run(bool fixedPolling)
        {
            var handler = new Handler();
            var client = Create(handler);
            var delays = new List<int>();
            SemaphoreSlim.ObserveWait = delay => {
                delays.Add(delay);
                if (delays.Count == 50) client.SendUpstreamMessageAsync(new object()).GetAwaiter().GetResult();
                if (delays.Count == 53) client.Stop();
            };
            try { await client.StartAsync(); }
            finally { SemaphoreSlim.ObserveWait = null; client.CloseTransport(); }
            Check(handler.SentActivity, "Outbound data was not sent");
            if (fixedPolling) Check(delays.TrueForAll(delay => delay == 100), "Fixed polling interval changed");
            else
            {
                Check(delays[0] >= 88 && delays[0] <= 132, "Wrong initial backoff");
                Check(delays[49] >= 8000 && delays[49] <= 12000, "Wrong idle cap");
                Check(delays[50] >= 80 && delays[50] <= 120, "Outbound activity did not reset backoff");
                Check(delays[51] >= 80 && delays[51] <= 120, "Inbound activity did not reset backoff");
            }

            foreach (string action in new[] { "send", "checkout", "close" })
            {
                client = Create(new Handler());
                var wake = (SemaphoreSlim)typeof(HttpServiceClient).GetField("_pollWake", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(client);
                var waiting = wake.WaitAsync(10000);
                if (action == "send") await client.SendUpstreamMessageAsync(new object());
                else if (action == "checkout") client.Stop();
                else client.CloseTransport();
                if (fixedPolling && action == "send")
                {
                    Check(!waiting.IsCompleted, "Fixed polling woke on data");
                    client.Stop();
                }
                Check(await Task.WhenAny(waiting, Task.Delay(500)) == waiting, action + " did not wake the wait");
                client.CloseTransport();
            }
            Console.WriteLine("PASS C# polling (" + (fixedPolling ? "fixed" : "adaptive") + ")");
        }

        static void Main(string[] args) { Run(args.Length > 0 && args[0] == "fixed").GetAwaiter().GetResult(); }
    }
}
