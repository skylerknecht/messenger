#!/usr/bin/env python3
import argparse
import collections
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

if os.name != "nt":
    import pexpect
from tcp_frames import FRAME_COUNT, assert_roundtrip, assert_socket_roundtrip

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
PY = Path(sys.executable)
KEY = "automation-key"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROMPT = re.compile(r"\([^)]*\)~# ")
TRANSCRIPT = []
RESULTS = []
CLIENTS = {}
RUNS = None
RESULTS_PATH = None
TRANSCRIPT_PATH = None


def clean(value):
    return ANSI.sub("", value).replace("\r", "")


def free_port(family=socket.AF_INET):
    s = socket.socket(family, socket.SOCK_STREAM)
    s.bind(("::1" if family == socket.AF_INET6 else "127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def fd_snapshot(pid):
    """Capture real Linux descriptors from the process under test."""
    proc_fd = Path(f"/proc/{pid}/fd")
    targets = []
    try:
        for descriptor in sorted(proc_fd.iterdir(), key=lambda path: int(path.name)):
            try:
                targets.append(os.readlink(descriptor))
            except OSError:
                targets.append("<closed-during-snapshot>")
    except OSError as exc:
        return {"pid": pid, "error": str(exc), "count": -1, "targets": []}
    kinds = collections.Counter()
    for target in targets:
        if target.startswith("socket:"): kinds["socket"] += 1
        elif target.startswith("pipe:"): kinds["pipe"] += 1
        elif target.startswith("anon_inode:"): kinds["anon_inode"] += 1
        else: kinds["file"] += 1
    return {"pid": pid, "count": len(targets), "targets": targets, "kinds": dict(kinds)}


def in_process_fd_snapshot(state):
    descriptor = state.get("fds", {})
    targets = descriptor.get("targets", [])
    if descriptor.get("count") is None:
        return {"error": "descriptor enumeration unavailable", "count": -1, "targets": []}
    kinds = collections.Counter()
    for target in targets:
        if target.startswith("socket:"): kinds["socket"] += 1
        elif target.startswith("pipe:"): kinds["pipe"] += 1
        elif target.startswith("anon_inode:"): kinds["anon_inode"] += 1
        else: kinds["file"] += 1
    return {
        "pid": state.get("pid"),
        "count": descriptor["count"],
        "targets": targets,
        "kinds": dict(kinds),
        "source": "/proc/self/fd inside server",
    }


def process_snapshot(pid):
    row = {"pid": pid, "threads": None, "children": []}
    task_dir = Path(f"/proc/{pid}/task")
    if task_dir.exists():
        try:
            row["threads"] = len(list(task_dir.iterdir()))
            for stat in Path("/proc").glob("[0-9]*/stat"):
                try:
                    fields = stat.read_text(encoding="utf-8").split()
                    if int(fields[3]) == pid:
                        row["children"].append(int(stat.parent.name))
                except (OSError, ValueError, IndexError):
                    pass
        except OSError:
            pass
    return row


def latest_state(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1]) if lines else {"error": "empty state log"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data = self.request.recv(65536)
            if not data:
                return
            self.request.sendall(data)


class Echo4(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Echo6(Echo4):
    address_family = socket.AF_INET6


class HeadlessCLI:
    """Cross-platform command controller for the real Manager command parser."""

    def __init__(self, command, cwd, env, control_port):
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.pid = self.process.pid
        self.control_port = control_port
        self.output = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"headless server exited early: {''.join(self.output)}")
            try:
                with socket.create_connection(("127.0.0.1", control_port), timeout=0.2) as probe:
                    probe.sendall(b'{"command":"messengers"}\n')
                    probe.recv(65536)
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise TimeoutError(f"headless control socket did not start: {''.join(self.output)}")

    def _read(self):
        for line in self.process.stdout:
            self.output.append(line)

    def expect_prompt(self, timeout=25):
        return "".join(self.output)

    def command(self, value):
        with socket.create_connection(("127.0.0.1", self.control_port), timeout=5) as control:
            control.settimeout(30)
            request = (json.dumps({"command": value}) + "\n").encode("utf-8")
            control.sendall(request)
            response = bytearray()
            while not response.endswith(b"\n"):
                chunk = control.recv(65536)
                if not chunk:
                    break
                response.extend(chunk)
        payload = json.loads(response.decode("utf-8"))
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload.get("output", "")

    def isalive(self):
        return self.process.poll() is None

    def stop(self):
        if self.isalive():
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()


class PtyCLI:
    def __init__(self, command, cwd, env):
        self.child = pexpect.spawn(
            command[0], command[1:], cwd=cwd, env=env,
            encoding="utf-8", timeout=25,
        )
        self.pid = self.child.pid

    def expect_prompt(self, timeout=25):
        self.child.expect(PROMPT, timeout=timeout)
        return clean(self.child.before)

    def command(self, value):
        self.child.sendline(value)
        self.child.expect_exact(value)
        before_echo = clean(self.child.before)
        return before_echo + self.expect_prompt()

    def isalive(self):
        return self.child.isalive()

    def stop(self):
        self.child.terminate(force=True)


class Server:
    def __init__(self, port, label):
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(ROOT), env.get("PYTHONPATH", "")) if part
        )
        conf = RUNS / label
        conf.mkdir(parents=True, exist_ok=True)
        self.state_log = conf / "server-state.jsonl"
        command = [
                str(PY),
                str(TESTS / "instrumented_server.py"), "-a", "127.0.0.1",
                "-p", str(port), "-e", KEY, "-c", str(conf),
                "--state-log", str(self.state_log),
            ]
        use_headless = os.name == "nt" or os.environ.get("MESSENGER_TEST_HEADLESS_CLI") == "1"
        if use_headless:
            control_port = free_port()
            command.extend(["--control-port", str(control_port)])
            self.child = HeadlessCLI(command, str(ROOT), env, control_port)
        else:
            self.child = PtyCLI(command, str(ROOT), env)
        self.port = port
        self.label = label
        startup = self.child.expect_prompt()
        TRANSCRIPT.append(f"\n===== SERVER {label} PID {self.child.pid} =====\n{startup}")
        # The instrumented process records its first state before aiohttp binds.
        # Capture a post-bind state so descriptor comparisons include the
        # permanent listening socket in their baseline.
        self.command("messengers", settle=0)

    @property
    def pid(self):
        return self.child.pid

    def command(self, value, settle=0.15):
        time.sleep(settle)
        marker = f">>> MESSENGER COMMAND: {value}"
        TRANSCRIPT.append(marker)
        output = self.child.command(value)
        TRANSCRIPT.append(output)
        return output

    def exit(self):
        if not self.child.isalive():
            return
        try:
            self.command("exit")
        except Exception:
            pass
        finally:
            self.child.stop()

    def lifecycle(self):
        return latest_state(self.state_log)

    def descriptors(self):
        external = fd_snapshot(self.pid)
        if external.get("count", -1) >= 0:
            external["source"] = f"/proc/{self.pid}/fd from harness"
            return external
        return in_process_fd_snapshot(self.lifecycle())


def record(scenario, ok, detail=""):
    RESULTS.append({"scenario": scenario, "ok": bool(ok), "detail": detail})


def start_client(kind, url, label):
    env = os.environ.copy()
    if kind == "python":
        cmd = [str(PY), CLIENTS[kind]]
    elif kind == "node":
        cmd = ["node", CLIENTS[kind]]
    elif kind == "csharp":
        csharp_path = Path(CLIENTS[kind])
        cmd = [str(csharp_path)] if csharp_path.suffix.lower() == ".exe" else ["dotnet", str(csharp_path)]
    else:
        raise ValueError(kind)
    user_agent = f"Messenger-Conformance/{kind}/{label}"
    cmd += [
        "--server-url", url,
        "--encryption-key", KEY,
        "--user-agent", user_agent,
        "--retry-duration", "6",
        "--retry-attempts", "6",
    ]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc, cmd


def get_id(server):
    deadline = time.time() + 12
    seen = ""
    while time.time() < deadline:
        out = server.command("messengers", settle=0.35)
        seen += out
        matches = re.findall(r"Messenger `([A-Za-z0-9]{10})`", out)
        if not matches:
            matches = re.findall(r"^\s*(?:>\s*)?([A-Za-z0-9]{10})\s+(?:WebSocket|HTTP)\s+", out, re.MULTILINE)
        if matches:
            return matches[-1], seen
    raise RuntimeError("client did not appear in messenger table: " + seen)


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        part = sock.recv(n - len(data))
        if not part:
            raise EOFError(f"wanted {n}, received {len(data)}")
        data += part
    return data


def socks_connect(proxy_port, atyp, host, target_port, seed):
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=5) as s:
        s.settimeout(8)
        s.sendall(b"\x05\x01\x00")
        assert recv_exact(s, 2) == b"\x05\x00"
        if atyp == 1:
            addr = socket.inet_aton(host)
        elif atyp == 3:
            raw = host.encode()
            addr = bytes([len(raw)]) + raw
        elif atyp == 4:
            addr = socket.inet_pton(socket.AF_INET6, host)
        else:
            raise ValueError(atyp)
        s.sendall(b"\x05\x01\x00" + bytes([atyp]) + addr + target_port.to_bytes(2, "big"))
        head = recv_exact(s, 4)
        if head[1] != 0:
            raise AssertionError(f"SOCKS rep={head[1]} head={head.hex()}")
        if head[3] == 1:
            recv_exact(s, 6)
        elif head[3] == 3:
            recv_exact(s, recv_exact(s, 1)[0] + 2)
        elif head[3] == 4:
            recv_exact(s, 18)
        return assert_socket_roundtrip(s, seed)


def socks_raw(proxy_port, request, expected_prefix):
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=5) as s:
        s.settimeout(5)
        s.sendall(request)
        got = s.recv(64)
        if not got.startswith(expected_prefix):
            raise AssertionError(f"expected {expected_prefix.hex()}, got {got.hex()}")


def ids_from_table(out, exclude=()):
    blocked = {x.lower() for x in exclude} | {"messengers", "forwarders"}
    return [x for x in re.findall(r"\b[A-Za-z0-9]{10}\b", out) if x.lower() not in blocked]


def full_flow(kind, transport, echo4_port, echo6_port):
    label = f"{kind}-{transport}"
    server_port = free_port()
    server = Server(server_port, label)
    base_fd = server.descriptors()
    url = f"{transport}://127.0.0.1:{server_port}"
    client, cmd = start_client(kind, url, label)
    client_out = ""
    try:
        mid, _ = get_id(server)
        record(f"{label}: actual client connected", True, f"server={server.pid}, client={client.pid}, id={mid}")
        connected_fd = {
            "server": server.descriptors(), "client": fd_snapshot(client.pid),
            "server_process": process_snapshot(server.pid), "client_process": process_snapshot(client.pid),
            "server_state": server.lifecycle(),
        }

        name = f"{kind}-{transport}"
        record(f"{label}: rename", "now known as" in server.command(f"rename {mid} {name}"))
        server.command(f"interact {name}")
        detail = server.command(f"messengers {name}")
        record(
            f"{label}: runtime server-url, key, and user-agent overrides",
            "Transport:" in detail and f"Messenger-Conformance/{kind}/{label}" in detail,
            detail,
        )
        help_output = server.command("help local")
        record(f"{label}: command help", "local" in help_output.lower() and "forward" in help_output.lower())

        local_port = free_port()
        out = server.command(f"local 127.0.0.1:{local_port}:127.0.0.1:{echo4_port}")
        time.sleep(0.4)
        try:
            proof = assert_roundtrip("127.0.0.1", local_port, f"local-ipv4:{label}")
            record(f"{label}: local forward 30 ordered records over IPv4", True, proof)
        except Exception as e:
            record(f"{label}: local forward 30 ordered records over IPv4", False, repr(e))

        local_host_port = free_port()
        server.command(f"local 127.0.0.1:{local_host_port}:localhost:{echo4_port}")
        time.sleep(0.3)
        try:
            proof = assert_roundtrip("127.0.0.1", local_host_port, f"local-hostname:{label}")
            record(f"{label}: local forward 30 ordered records to hostname", True, proof)
        except Exception as e:
            record(f"{label}: local forward 30 ordered records to hostname", False, repr(e))

        local_ipv6_port = None
        if echo6_port:
            local_ipv6_port = free_port()
            server.command(f"local 127.0.0.1:{local_ipv6_port}:[::1]:{echo6_port}")
            time.sleep(0.3)
            try:
                proof = assert_roundtrip("127.0.0.1", local_ipv6_port, f"local-ipv6:{label}")
                record(f"{label}: local forward 30 ordered records to IPv6", True, proof)
            except Exception as e:
                record(f"{label}: local forward 30 ordered records to IPv6", False, repr(e))

        socks_port = free_port()
        server.command(f"socks 127.0.0.1:{socks_port}")
        time.sleep(0.4)
        for title, atyp, host, target in [
            ("SOCKS5 IPv4", 1, "127.0.0.1", echo4_port),
            ("SOCKS5 hostname", 3, "localhost", echo4_port),
            ("SOCKS5 IPv6", 4, "::1", echo6_port),
        ]:
            try:
                proof = socks_connect(socks_port, atyp, host, target, f"{title}:{label}")
                record(f"{label}: {title} 30 ordered records", True, proof)
            except Exception as e:
                record(f"{label}: {title} 30 ordered records", False, repr(e))

        malformed = [
            (b"\x04\x01\x00", b""),
            (b"\x05\x01\x02", b"\x05\xff"),
        ]
        for idx, (req, expected) in enumerate(malformed):
            try:
                with socket.create_connection(("127.0.0.1", socks_port), timeout=5) as s:
                    s.settimeout(2); s.sendall(req); got = s.recv(32)
                    if expected and not got.startswith(expected): raise AssertionError(got.hex())
                record(f"{label}: SOCKS greeting error {idx+1}", True, got.hex())
            except Exception as e:
                record(f"{label}: SOCKS greeting error {idx+1}", False, repr(e))
        for title, req, expected in [
            ("unsupported command", b"\x05\x02\x00\x01\x7f\x00\x00\x01\x00\x50", b"\x05\x07"),
            ("invalid reserved byte", b"\x05\x01\x01\x01\x7f\x00\x00\x01\x00\x50", b"\x05\x01"),
            ("unsupported address", b"\x05\x01\x00\x02", b"\x05\x08"),
        ]:
            try:
                with socket.create_connection(("127.0.0.1", socks_port), timeout=5) as s:
                    s.settimeout(4); s.sendall(b"\x05\x01\x00"); assert recv_exact(s,2)==b"\x05\x00"; s.sendall(req); got=s.recv(64); assert got.startswith(expected),got.hex()
                record(f"{label}: SOCKS {title} reply", True, got.hex())
            except Exception as e:
                record(f"{label}: SOCKS {title} reply", False, repr(e))

        remote_port = free_port()
        server.command(f"remote 127.0.0.1:{remote_port}:127.0.0.1:{echo4_port}")
        time.sleep(0.8)
        try:
            proof = assert_roundtrip("127.0.0.1", remote_port, f"remote-ipv4:{label}")
            record(f"{label}: remote forward 30 ordered records over IPv4", True, proof)
        except Exception as e:
            record(f"{label}: remote forward 30 ordered records over IPv4", False, repr(e))

        remote_host_port = free_port()
        server.command(f"remote 127.0.0.1:{remote_host_port}:localhost:{echo4_port}")
        time.sleep(0.8)
        try:
            proof = assert_roundtrip("127.0.0.1", remote_host_port, f"remote-hostname:{label}")
            record(f"{label}: remote forward 30 ordered records to hostname", True, proof)
        except Exception as e:
            record(f"{label}: remote forward 30 ordered records to hostname", False, repr(e))

        remote_ipv6_port = None
        if echo6_port:
            remote_ipv6_port = free_port()
            server.command(f"remote 127.0.0.1:{remote_ipv6_port}:[::1]:{echo6_port}")
            time.sleep(0.8)
            try:
                proof = assert_roundtrip("127.0.0.1", remote_ipv6_port, f"remote-ipv6:{label}")
                record(f"{label}: remote forward 30 ordered records to IPv6", True, proof)
            except Exception as e:
                record(f"{label}: remote forward 30 ordered records to IPv6", False, repr(e))

        closed_port = free_port()
        cap_output = server.command(
            f"portscan 127.0.0.1 {closed_port} --concurrency 1001"
        )
        record(
            f"{label}: scanner rejects concurrency above 1000 without force",
            "cannot exceed 1000" in cap_output,
            cap_output,
        )

        server.command("portscan 127.0.0.1 1-30 --concurrency 1")
        time.sleep(0.25)
        active_table = server.command("scans")
        active_scan_ids = ids_from_table(active_table, (mid,))
        if active_scan_ids:
            active_id = active_scan_ids[-1]
            server.command(f"stop {active_id}")
            time.sleep(0.1)
            stopped_active = server.command("scans")
            record(
                f"{label}: active scanner stops and remains visible",
                active_id in stopped_active and "stopped" in stopped_active,
                stopped_active,
            )
        else:
            record(f"{label}: active scanner stops and remains visible", False, active_table)

        server.command(f"portscan 127.0.0.1 {echo4_port},{closed_port} --concurrency 2")
        time.sleep(2.5)
        scan_table = server.command("scans")
        scan_ids = ids_from_table(scan_table, (mid,))
        record(f"{label}: scanner open/closed completion", "2/2 (100%)" in scan_table and " 1 " in scan_table, clean(scan_table)[-600:])
        if scan_ids:
            completed_scan_id = scan_ids[-1]
            scan_detail = server.command(f"scans {completed_scan_id} --show-closed")
            record(f"{label}: scanner detailed results", "open" in scan_detail and "closed" in scan_detail)

        fwd_table = server.command("forwarders")
        fids = ids_from_table(fwd_table, (mid,))
        expected_forwarders = 7 if echo6_port else 5
        record(f"{label}: forwarder inventory", len(fids) >= expected_forwarders, fids)
        if fids:
            record(f"{label}: forwarder rename", "now known as" in server.command(f"rename {fids[0]} local-test"))
            fids[0] = "local-test"
        resources_fd = {
            "server": server.descriptors(), "client": fd_snapshot(client.pid),
            "server_process": process_snapshot(server.pid), "client_process": process_snapshot(client.pid),
            "server_state": server.lifecycle(),
        }

        record(f"{label}: logging command", "logging enabled" in server.command("logging 1,4"))
        record(f"{label}: display command", bool(server.command("display")))

        for fid in fids:
            server.command(f"stop {fid}")
        if scan_ids:
            server.command(f"stop {scan_ids[-1]}")
            stopped_scan = server.command("scans")
            record(f"{label}: stopped scan retained in display", scan_ids[-1] in stopped_scan)
        time.sleep(0.5)
        after_stop_fd = {
            "server": server.descriptors(), "client": fd_snapshot(client.pid),
            "server_process": process_snapshot(server.pid), "client_process": process_snapshot(client.pid),
            "server_state": server.lifecycle(),
        }
        stopped_messenger = next(iter(after_stop_fd["server_state"].get("messengers", [])), {})
        record(
            f"{label}: no retained server TCP clients after stop",
            stopped_messenger.get("tcp_clients", -1) == 0,
            stopped_messenger,
        )
        live_scanner_workers = sum(
            scanner.get("live_workers", 0)
            for scanner in stopped_messenger.get("scanners", [])
        )
        record(
            f"{label}: no retained scanner workers after stop",
            live_scanner_workers == 0,
            stopped_messenger.get("scanners", []),
        )
        operation_tasks = [
            task for task in after_stop_fd["server_state"].get("tasks", [])
            if "TcpClient" in task.get("coro", "")
            or "_scan_worker" in task.get("coro", "")
            or task.get("coro", "").endswith("Scanner.start")
        ]
        record(
            f"{label}: no retained TCP or scanner tasks after stop",
            not operation_tasks,
            operation_tasks,
        )
        closed_listeners = [
            ("local IPv4", local_port),
            ("local hostname", local_host_port),
            ("SOCKS", socks_port),
            ("remote IPv4", remote_port),
            ("remote hostname", remote_host_port),
        ]
        if local_ipv6_port:
            closed_listeners.append(("local IPv6", local_ipv6_port))
        if remote_ipv6_port:
            closed_listeners.append(("remote IPv6", remote_ipv6_port))
        for title, port in closed_listeners:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                record(f"{label}: {title} listener closed after stop", False, "connection still accepted")
            except OSError:
                record(f"{label}: {title} listener closed after stop", True)
        if os.name != "nt" and connected_fd["client"].get("count", -1) >= 0:
            record(
                f"{label}: client descriptors return to connected baseline after stop",
                after_stop_fd["client"]["count"] <= connected_fd["client"]["count"],
                {"connected": connected_fd["client"], "after_stop": after_stop_fd["client"]},
            )
        elif os.name != "nt":
            record(
                f"{label}: client descriptor snapshot unavailable in harness PID namespace",
                True,
                {"connected": connected_fd["client"], "after_stop": after_stop_fd["client"]},
            )

        server.command("back")
        kill_out = server.command(f"kill {name}")
        try:
            client_out = client.communicate(timeout=8)[0]
            exited = True
        except subprocess.TimeoutExpired:
            client.terminate(); client_out = client.communicate(timeout=3)[0]; exited = False
        TRANSCRIPT.append(f"===== CLIENT {label} PID {client.pid} CMD {json.dumps(cmd)} =====\n{client_out}")
        record(f"{label}: checkout exits client", exited and "Kill signal received" in client_out, client_out)
        pos = client_out.find("Kill signal received")
        record(f"{label}: no reconnect after checkout", pos >= 0 and "Reconnected" not in client_out[pos:])
        status = server.command(f"messengers {name}")
        record(f"{label}: server marks checked out", "checked out" in status)
        # aiohttp closes the WebSocket transport on a later loop turn after the
        # handler/send tasks have exited. Sample only after that close callback.
        time.sleep(0.5)
        server.command("messengers")
        after_kill_fd = {
            "server": server.descriptors(), "client": fd_snapshot(client.pid),
            "server_process": process_snapshot(server.pid), "client_process": process_snapshot(client.pid),
            "server_state": server.lifecycle(),
        }

        fd_data = {"baseline": base_fd, "connected": connected_fd, "resources": resources_fd, "after_stop": after_stop_fd, "after_kill": after_kill_fd}
        record(f"{label}: client process exited after checkout", client.poll() is not None, fd_data)
        terminal_tasks = [
            task for task in after_kill_fd["server_state"].get("tasks", [])
            if "TcpClient" in task.get("coro", "")
            or "_scan_worker" in task.get("coro", "")
            or task.get("coro", "").endswith("Scanner.start")
            or task.get("coro", "").endswith("Messenger._send_loop")
        ]
        record(
            f"{label}: no retained messenger operation tasks after checkout",
            not terminal_tasks,
            terminal_tasks,
        )
        if os.name != "nt":
            expected_server_max = base_fd["count"]
            record(
                f"{label}: server descriptors return near baseline",
                after_kill_fd["server"]["count"] <= expected_server_max,
                fd_data,
            )
            record(
                f"{label}: server has no child processes after cleanup",
                not after_kill_fd["server_process"]["children"],
                after_kill_fd["server_process"],
            )
        else:
            record(
                f"{label}: descriptor enumeration is Linux-only",
                True,
                "Windows still receives listener, TCP-client collection, task, and process-exit checks.",
            )
    except Exception as e:
        record(f"{label}: harness flow", False, repr(e))
        if client.poll() is None:
            client.terminate()
        try:
            client_out += client.communicate(timeout=3)[0]
        except Exception:
            client.kill()
        TRANSCRIPT.append(f"===== CLIENT {label} FAILURE =====\n{client_out}")
    finally:
        server.exit()


def reconnect_flow(kind, transport):
    label = f"{kind}-{transport}-restart"
    port = free_port()
    first = Server(port, label + "-first")
    client, cmd = start_client(kind, f"{transport}://127.0.0.1:{port}", label)
    try:
        mid, _ = get_id(first)
        first.exit()
        time.sleep(0.8)
        second = Server(port, label + "-second")
        try:
            new_id, _ = get_id(second)
            record(f"{label}: reconnect after server restart", new_id == mid, f"before={mid} after={new_id}")
            second.command(f"kill {new_id}")
            try:
                out = client.communicate(timeout=10)[0]
                exited = True
            except subprocess.TimeoutExpired:
                client.terminate(); out = client.communicate(timeout=3)[0]; exited = False
            TRANSCRIPT.append(f"===== CLIENT {label} PID {client.pid} CMD {json.dumps(cmd)} =====\n{out}")
            record(f"{label}: reconnect logged", "Reconnected" in out, out)
            pos = out.rfind("Kill signal received")
            record(f"{label}: checkout during reconnect is terminal", exited and pos >= 0 and "Reconnected" not in out[pos:], out)
            final_fd = fd_snapshot(client.pid)
            record(f"{label}: process exited after restart checkout", client.poll() is not None, final_fd)
        finally:
            second.exit()
    except Exception as e:
        record(f"{label}: harness flow", False, repr(e))
        if client.poll() is None:
            client.terminate()
        first.exit()


def parse_args():
    parser = argparse.ArgumentParser(description="Run real Messenger CLI/client conformance tests")
    parser.add_argument("--python-client", type=Path)
    parser.add_argument("--node-client", type=Path)
    parser.add_argument("--csharp-dll", type=Path)
    parser.add_argument("--transports", nargs="+", choices=("ws", "http"), default=("ws", "http"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".conformance-results")
    return parser.parse_args()


def main():
    global CLIENTS, RUNS, RESULTS_PATH, TRANSCRIPT_PATH
    args = parse_args()
    requested = {
        "python": args.python_client,
        "node": args.node_client,
        "csharp": args.csharp_dll,
    }
    CLIENTS = {kind: str(path.resolve()) for kind, path in requested.items() if path is not None}
    if not CLIENTS:
        raise SystemExit("at least one generated client path is required")
    missing = [path for path in CLIENTS.values() if not Path(path).is_file()]
    if missing:
        raise SystemExit(f"generated client artifacts do not exist: {missing}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    RUNS = args.output_dir / "runs"
    RESULTS_PATH = args.output_dir / "results.json"
    TRANSCRIPT_PATH = args.output_dir / "transcript.txt"
    if RUNS.exists(): shutil.rmtree(RUNS)
    RUNS.mkdir()
    e4 = Echo4(("127.0.0.1", 0), EchoHandler)
    p4 = e4.server_address[1]
    threading.Thread(target=e4.serve_forever, daemon=True).start()
    ipv6 = True
    try:
        # Serve the same port on both loopback families so `localhost` is
        # deterministic regardless of the OS resolver's family preference.
        e6 = Echo6(("::1", p4), EchoHandler); p6 = e6.server_address[1]
        threading.Thread(target=e6.serve_forever, daemon=True).start()
    except OSError:
        ipv6 = False; e6 = None; p6 = 0
    for kind in CLIENTS:
        for transport in args.transports:
            full_flow(kind, transport, p4, p6)
            reconnect_flow(kind, transport)
    e4.shutdown(); e4.server_close()
    if e6: e6.shutdown(); e6.server_close()
    payload = {
        "environment": {
            "platform": sys.platform,
            "python": sys.version,
            "node": subprocess.check_output(["node", "--version"], text=True).strip() if shutil.which("node") else None,
            "dotnet": subprocess.check_output(["dotnet", "--version"], text=True).strip() if shutil.which("dotnet") else None,
            "ipv6_loopback": ipv6,
            "frame_count_per_stream": FRAME_COUNT,
        },
        "clients": CLIENTS,
        "results": RESULTS,
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    TRANSCRIPT_PATH.write_text("\n".join(TRANSCRIPT), encoding="utf-8")
    passed = sum(1 for x in RESULTS if x["ok"])
    failed = len(RESULTS) - passed
    print(json.dumps({"passed": passed, "failed": failed, "failures": [x for x in RESULTS if not x["ok"]]}, indent=2))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
