import ipaddress
import asyncio
import time
import os
from collections import namedtuple

from messenger.generator import alphanumeric_identifier
from messenger.message import InitiateTCPClientReq, SendDataMessage

ScanResult = namedtuple("ScanResult", ["identifier", "address", "port", "result"])

class Scanner:
    def __init__(self, ip_ranges, port_ranges, top_ports, update_cli, messenger, concurrency):
        self.identifier = alphanumeric_identifier()
        self._nickname = None
        self.ip_input = ip_ranges
        self.port_input = port_ranges
        self.update_cli = update_cli
        self.messenger = messenger
        self.concurrency = concurrency
        self.targets = self._parse_ip_ranges(ip_ranges)
        self.ports = self._parse_port_ranges(port_ranges) if port_ranges else self._get_top_ports(top_ports)
        self.scans = {}
        self.start_time = None
        self.end_time = None
        self.semaphore = asyncio.Semaphore(concurrency)
        self._gen_lock = asyncio.Lock()
        self._scan_gen = self._generate_scans()
        self._workers = []

    @property
    def nickname(self):
        return self._nickname or self.identifier

    @nickname.setter
    def nickname(self, value):
        self._nickname = value

    @staticmethod
    def _get_top_ports(n):
        base_dir = os.path.dirname(__file__)
        path = os.path.join(base_dir, 'resources', 'top_ports.txt')

        with open(path, 'r') as file:
            ranked_ports = [int(line.strip()) for line in file if line.strip().isdigit()]

        seen = set(ranked_ports)
        all_ports = ranked_ports.copy()

        for port in range(1, 65536):
            if port not in seen:
                all_ports.append(port)
            if len(all_ports) >= n:
                break

        return all_ports[:n]

    def _parse_ip_ranges(self, raw):
        hosts = set()
        for part in raw.split(','):
            part = part.strip()
            if not part:
                continue

            # CIDR, e.g. 10.0.0.0/24
            if '/' in part:
                try:
                    net = ipaddress.ip_network(part, strict=False)
                    hosts.update(str(ip) for ip in net.hosts())
                except ValueError:
                    self.update_cli.display(f'Skipping invalid CIDR `{part}`.', 'warning', reprompt=False)
                continue

            # Last-octet range, e.g. 10.0.0.1-50
            base, _, end = part.rpartition('.')
            lo, dash, hi = end.partition('-')
            if base and dash and lo.isdigit() and hi.isdigit():
                start, stop = int(lo), int(hi)
                if 0 <= start <= stop <= 255:
                    hosts.update(f'{base}.{i}' for i in range(start, stop + 1))
                else:
                    self.update_cli.display(f'Skipping invalid range `{part}`.', 'warning', reprompt=False)
                continue

            # Single IP or hostname (may contain hyphens)
            hosts.add(part)

        return sorted(hosts)

    def _parse_port_ranges(self, raw):
        ports = set()
        for entry in raw.split(','):
            entry = entry.strip()
            if not entry:
                continue
            if '-' in entry:
                lo, _, hi = entry.partition('-')
                if lo.isdigit() and hi.isdigit() and int(lo) <= int(hi):
                    ports.update(range(int(lo), int(hi) + 1))
                else:
                    self.update_cli.display(f'Skipping invalid port range `{entry}`.', 'warning', reprompt=False)
            elif entry.isdigit():
                ports.add(int(entry))
            else:
                self.update_cli.display(f'Skipping invalid port `{entry}`.', 'warning', reprompt=False)
        return sorted(ports)

    def _generate_scans(self):
        for ip in self.targets:
            for port in self.ports:
                yield ip, port

    @property
    def total_scans(self) -> int:
        return len(self.targets) * len(self.ports)

    @property
    def attempts(self) -> int:
        return len(self.scans)

    @property
    def open_count(self) -> int:
        return sum(1 for s in self.scans.values() if s.result == 0)

    @property
    def closed_count(self) -> int:
        return sum(1 for s in self.scans.values() if s.result not in (0, None))

    @property
    def formatted_runtime(self) -> str:
        runtime = int((self.end_time or time.time()) - self.start_time)
        hours, minutes = divmod(runtime, 3600)
        minutes, seconds = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    @property
    def progress_str(self) -> str:
        progress = self.open_count + self.closed_count
        percent = (progress / self.total_scans) * 100 if self.total_scans else 0
        return f"{progress}/{self.total_scans} ({percent:.0f}%)"

    @property
    def completed(self) -> bool:
        progress = self.open_count + self.closed_count
        return progress == self.total_scans

    async def handle_initiate_tcp_client_rep(self, message):
        identifier = message.client_id
        current = self.scans.get(identifier)

        if current is None:
            return
        if current.result is not None:
            self.update_cli.display(
                f'FLIP {current.address}:{current.port} {current.result} -> {message.reason}, '
                f'please report this to https://github.com/skylerknecht/messenger/issues/31.',
                'warning'
            )
            return

        self.scans[identifier] = ScanResult(identifier, current.address, current.port, message.reason)
        self.semaphore.release()

        if message.reason == 0:
            await self.messenger.send_message_downstream(
                SendDataMessage(client_id=identifier, data=b'')
            )

        if not self.end_time and self.completed:
            self.end_time = time.time()
            readable = time.strftime("%H:%M:%S %Z", time.localtime(self.end_time))
            self.update_cli.display(
                f"Scan `{self.nickname}` completed at {readable}. All results received.", 'success'
            )

    async def _scan_worker(self):
        while True:
            async with self._gen_lock:
                try:
                    ip, port = next(self._scan_gen)
                except StopIteration:
                    return

            await self.semaphore.acquire()
            identifier = alphanumeric_identifier()
            self.scans[identifier] = ScanResult(identifier, ip, port, None)

            msg = InitiateTCPClientReq(
                client_id=identifier,
                destination_host=ip,
                destination_port=port
            )
            await self.messenger.send_message_downstream(msg)
            await asyncio.sleep(1)

    async def start(self):
        self.start_time = time.time()
        readable = time.strftime("%H:%M:%S %Z", time.localtime(self.start_time))
        self.update_cli.display(
            f"Starting scan `{self.nickname}` at {readable} with a concurrency of `{self.concurrency}`.", 'information',
        )

        self._workers = [asyncio.create_task(self._scan_worker()) for _ in range(self.concurrency)]
        await asyncio.gather(*self._workers)

        self.update_cli.display(
            f"Scanner `{self.nickname}` finished sending all scan attempts.", 'information',
        )

    async def stop(self):
        if self.end_time:
            self.update_cli.display(f"Scanner `{self.nickname}` already stopped sending scan attempts.", 'information', reprompt=False)
            return

        self.end_time = time.time()
        self.update_cli.display(f"Scanner `{self.nickname}` has stopped and no further scans attempts will be made. Existing attempts will still update as they arrive.", 'success', reprompt=False)
        for w in self._workers:
            w.cancel()

