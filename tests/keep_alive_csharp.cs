using System;
using System.Threading.Tasks;

class KeepAliveTest : ServiceClient.ServiceClient
{
    private int _sent;
    public override Task ConnectAsync() { return Task.CompletedTask; }
    public override Task StartAsync() { return Task.CompletedTask; }
    public override Task SendUpstreamMessageAsync(object message) { _sent++; return Task.CompletedTask; }
    public override void CloseTransport() { }

    static byte[] Decode(string hex)
    {
        var bytes = new byte[hex.Length / 2];
        for (int i = 0; i < bytes.Length; i++) bytes[i] = Convert.ToByte(hex.Substring(i * 2, 2), 16);
        return bytes;
    }

    static void Main(string[] args)
    {
        var client = new KeepAliveTest();
        foreach (var message in DeserializeMessages(Decode(args[1]), Decode(args[0]))) client.DispatchMessage(message);
        if (client.TcpClients.Count != 0 || client.Killed || client._sent != 0)
            throw new Exception("Keep-alive must be discarded without creating a TCP connection");
        Console.WriteLine("PASS C#: encrypted keep-alive discarded without creating a TCP connection");
    }
}
