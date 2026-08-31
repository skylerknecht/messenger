#!/usr/bin/env python3
"""Run the real Messenger CLI while emitting test-only lifecycle snapshots."""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from messenger.manager import Manager
from messenger.text import strip_ansi


class InstrumentedManager(Manager):
    state_log: Path

    def snapshot(self, event, command=None):
        descriptor_targets = []
        fd_dir = Path("/proc/self/fd")
        if fd_dir.exists():
            for descriptor in sorted(fd_dir.iterdir(), key=lambda path: int(path.name)):
                try:
                    descriptor_targets.append(os.readlink(descriptor))
                except OSError:
                    descriptor_targets.append("<closed-during-snapshot>")
        task_rows = []
        for task in asyncio.all_tasks():
            if task.done():
                continue
            coro = task.get_coro()
            task_rows.append({
                "name": task.get_name(),
                "coro": getattr(coro, "__qualname__", type(coro).__name__),
                "cancelled": task.cancelled(),
            })

        messengers = []
        for messenger in self.messengers:
            forwarders = []
            for forwarder in messenger.forwarders:
                forwarders.append({
                    "id": forwarder.identifier,
                    "type": type(forwarder).__name__,
                    "stopped": bool(getattr(forwarder, "stopped", False)),
                    "clients": len(getattr(forwarder, "clients", [])),
                    "server_closing": bool(
                        getattr(forwarder, "server", None)
                        and forwarder.server.is_serving() is False
                    ),
                })
            scanners = []
            for scanner in messenger.scanners:
                workers = list(getattr(scanner, "_workers", []))
                scanners.append({
                    "id": scanner.identifier,
                    "state": scanner.state,
                    "pending": sum(1 for result in scanner.scans.values() if result.result is None),
                    "workers": len(workers),
                    "live_workers": sum(1 for worker in workers if not worker.done()),
                })
            messengers.append({
                "id": messenger.identifier,
                "checked_out": messenger.checked_out,
                "queued_downstream": messenger.downstream_messages.qsize(),
                "tcp_clients": sum(row["clients"] for row in forwarders),
                "forwarders": forwarders,
                "scanners": scanners,
            })

        row = {
            "time": time.time(),
            "event": event,
            "command": command,
            "pid": os.getpid(),
            "fds": {
                "count": len(descriptor_targets) if fd_dir.exists() else None,
                "targets": descriptor_targets,
            },
            "tasks": task_rows,
            "messengers": messengers,
        }
        self.state_log.parent.mkdir(parents=True, exist_ok=True)
        with self.state_log.open("a", encoding="utf-8") as output:
            output.write(json.dumps(row, sort_keys=True) + "\n")

    async def execute_command(self, command, tokens):
        if command == "exit":
            self.snapshot("before-exit", command)
        try:
            return await super().execute_command(command, tokens)
        finally:
            if command != "exit":
                # Let immediate close callbacks and cancelled tasks settle.
                await asyncio.sleep(0)
                self.snapshot("after-command", " ".join([command, *tokens]))


async def run(args):
    manager = InstrumentedManager(
        args.address,
        args.port,
        None,
        args.encryption_key,
        args.config,
        set(),
        None,
        False,
        False,
        True,
    )
    manager.state_log = Path(args.state_log)
    manager.snapshot("startup")
    if args.control_port:
        await manager.messenger_server.start()
        stopped = asyncio.Event()

        async def execute(reader, writer):
            try:
                request = json.loads((await reader.readline()).decode("utf-8"))
                command_line = request["command"].strip()
                if command_line == "exit":
                    manager.snapshot("before-exit", command_line)
                    response = {"output": "Messenger Server stopped.\n"}
                    stopped.set()
                else:
                    parts = command_line.split()
                    timestamp = manager.logger.now()
                    with manager.logger.capture() as output:
                        await manager.execute_command(parts[0], parts[1:])
                    captured = strip_ansi(output.getvalue()).strip()
                    manager.logger.record_command(timestamp, command_line, captured)
                    response = {"output": captured + ("\n" if captured else "")}
                writer.write((json.dumps(response) + "\n").encode("utf-8"))
                await writer.drain()
            except Exception as error:
                writer.write((json.dumps({"error": repr(error)}) + "\n").encode("utf-8"))
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        controller = await asyncio.start_server(execute, "127.0.0.1", args.control_port)
        print(f"TEST CONTROL READY {args.control_port}", flush=True)
        await stopped.wait()
        controller.close()
        await controller.wait_closed()
    else:
        await manager.start_command_line_interface()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--address", default="127.0.0.1")
    parser.add_argument("-p", "--port", type=int, required=True)
    parser.add_argument("-e", "--encryption-key", required=True)
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("--state-log", required=True)
    parser.add_argument("--control-port", type=int)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
