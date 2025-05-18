import ipaddress
import asyncio
import time
from collections import namedtuple

from messenger.generator import alphanumeric_identifier
from messenger.message import InitiateForwarderClientReq

ScanResult = namedtuple("ScanResult", ["identifier", "address", "port", "result"])

class Scanner:
    def __init__(self, ip_ranges, port_ranges, update_cli, messenger, concurrency=50):
        self.identifier = alphanumeric_identifier()
        self.ip_input = ip_ranges
        self.port_input = port_ranges
        self.targets = self._parse_ip_ranges(ip_ranges)
        self.ports = self._parse_port_ranges(port_ranges)
        self.update_cli = update_cli
        self.messenger = messenger
        self.scans = {}
        self.start_time = None
        self.end_time = None
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        self._gen_lock = asyncio.Lock()
        self._scan_gen = self._generate_scans()
        self._workers = []
        self._scanning = False

    def _parse_ip_ranges(self, raw):
        hosts = set()
        parts = raw.split(',')
        for part in parts:
            part = part.strip()
            if '/' in part:
                try:
                    net = ipaddress.ip_network(part, strict=False)
                    hosts.update(str(ip) for ip in net.hosts())
                except ValueError:
                    continue
            elif '-' in part:
                base, end = part.rsplit('.', 1)
                start, stop = map(int, end.split('-'))
                for i in range(start, stop + 1):
                    hosts.add(f"{base}.{i}")
            else:
                hosts.add(part)
        return sorted(hosts)

    def _parse_port_ranges(self, raw):
        ports = set()
        for entry in raw.split(','):
            entry = entry.strip()
            if '-' in entry:
                start, stop = map(int, entry.split('-'))
                ports.update(range(start, stop + 1))
            elif entry.isdigit():
                ports.add(int(entry))
        return sorted(ports)

    def _generate_scans(self):
        for ip in self.targets:
            for port in self.ports:
                yield ip, port

    @property
    def total_scans(self) -> int:
        return len(self.targets) * len(self.ports)

    def update_result(self, identifier, result):
        if identifier in self.scans:
            current = self.scans[identifier]
            self.scans[identifier] = ScanResult(identifier, current.address, current.port, result)
        self.semaphore.release()

    async def _scan_worker(self):
        while self._scanning:
            async with self._gen_lock:
                try:
                    ip, port = next(self._scan_gen)
                except StopIteration:
                    return

            await self.semaphore.acquire()
            identifier = alphanumeric_identifier()
            self.scans[identifier] = ScanResult(identifier, ip, port, None)

            msg = InitiateForwarderClientReq(
                forwarder_client_id=identifier,
                ip_address=ip,
                port=port
            )
            await self.messenger.send_message_upstream(msg)
            await asyncio.sleep(1)

    async def start(self):
        self._scanning = True
        self.start_time = time.time()
        readable = time.strftime("%H:%M:%S %Z", time.localtime(self.start_time))
        self.update_cli.display(
            f"Starting scan `{self.identifier}` at {readable}", 'information',
        )

        self._workers = [asyncio.create_task(self._scan_worker()) for _ in range(self.concurrency)]
        await asyncio.gather(*self._workers)

        self.end_time = time.time()
        readable = time.strftime("%H:%M:%S %Z", time.localtime(self.end_time))
        self.update_cli.display(
            f"Finished scan `{self.identifier}` at {readable}", 'success',
        )

    async def stop(self):
        if not self._scanning or self.end_time:
            self.update_cli.display(f"Scanner `{self.identifier}` has already finished.", 'information', reprompt=False)
            return
        self.update_cli.display(f"Stopping scan `{self.identifier}`", 'information', reprompt=False)
        self._scanning = False
