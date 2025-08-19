import asyncio
import builtins
import types
import pytest

@pytest.mark.asyncio
async def test_cli_script_with_fake_clients(monkeypatch):
    # Import from your real module
    from messenger.cli import Manager

    # ---- Build manager, but stub server start (no sockets in CI)
    mgr = Manager(server_ip="127.0.0.1", server_port=0, ssl=False, encryption_key="testkey")

    async def fake_server_start():
        # pretend server is listening; nothing to do for this unit-ish test
        return None

    monkeypatch.setattr(mgr.messenger_server, "start", fake_server_start)

    # ---- Capture UpdateCLI.display(...) messages
    displayed = []
    def fake_display(msg, status="standard", reprompt=True, debug_level=0):
        displayed.append((status, msg))
    monkeypatch.setattr(mgr.update_cli, "display", fake_display)

    # ---- Capture 'print(...)' (tables, help, banners) so we can assert on them, too.
    printed = []
    def fake_print(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        printed.append(text)
    monkeypatch.setattr(builtins, "print", fake_print)

    # ---- Provide a fake connected Messenger object (no network)
    class FakeMessenger:
        transport_type = "ws"
        alive = True
        scanners = []
        forwarders = []
        sent = 0
        received = 0
        def __init__(self, identifier="ABC123"):
            self.identifier = identifier
        def format_sent_bytes(self): return "0 B"
        def format_received_bytes(self): return "0 B"

    m = FakeMessenger()
    mgr.messengers.append(m)

    # ---- Monkeypatch forwarder classes to fakes so 'local/remote/socks' work
    # They only need attributes used by your table/stop logic.
    class _BaseFakeForwarder:
        NAME = "Fake"
        def __init__(self, messenger, cfg, update_cli):
            self.messenger = messenger
            self.cfg = cfg
            self.update_cli = update_cli
            self.identifier = "FWD1"
            self.clients = []          # list of objs with .streaming if you want to show active clients
            # Fill table fields:
            self.listening_host = "127.0.0.1"
            self.listening_port = 9000
            self.destination_host = "1.2.3.4"
            self.destination_port = 80
        async def start(self): return True
        async def stop(self): return None

    class FakeLocal(_BaseFakeForwarder):
        NAME = "LocalPortForwarder"

    class FakeRemote(_BaseFakeForwarder):
        NAME = "RemotePortForwarder"

    class FakeSocks(_BaseFakeForwarder):
        NAME = "SocksProxy"

    import messenger.cli as cli_mod
    monkeypatch.setattr(cli_mod, "LocalPortForwarder", FakeLocal, raising=True)
    monkeypatch.setattr(cli_mod, "RemotePortForwarder", FakeRemote, raising=True)
    monkeypatch.setattr(cli_mod, "SocksProxy",       FakeSocks, raising=True)

    # ---- Feed commands through the async prompt
    # (Your loop splits by spaces, so these map 1:1.)
    cmds = iter([
        "help",
        "messengers",
        m.identifier,                      # enter interact mode
        "local 127.0.0.1:9000:1.2.3.4:80", # create a fake local forwarder
        "forwarders",
        "stop FWD1",
        "exit"
    ])

    async def fake_prompt_async(_prompt):
        try:
            return next(cmds)
        except StopIteration:
            # If 'exit' didn't trigger, abort the loop gracefully
            raise asyncio.CancelledError

    monkeypatch.setattr(mgr.session, "prompt_async", fake_prompt_async)

    # ---- Run the CLI loop and expect SystemExit from your 'exit' command
    task = asyncio.create_task(mgr.start_command_line_interface())

    with pytest.raises(SystemExit) as se:
        await asyncio.wait_for(task, timeout=5)
    assert se.value.code == 0

    # ---- Assertions: we saw help, a messengers table, a forwarders table, and the stop message
    whole_output = "\n".join([msg for _, msg in displayed] + printed).lower()
    assert "server commands:" in whole_output
    assert "messengers" in whole_output
    assert m.identifier.lower() in whole_output
    assert "forwarders" in whole_output
    assert "removed `fwd1` from forwarders" in whole_output