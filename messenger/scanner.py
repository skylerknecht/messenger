import ipaddress
import asyncio
import time
from collections import namedtuple

from messenger.generator import alphanumeric_identifier
from messenger.message import InitiateForwarderClientReq

ScanResult = namedtuple("ScanResult", ["identifier", "address", "port", "result"])

class Scanner:
    def __init__(self, ip_ranges, port_ranges, update_cli, messenger):
        self.identifier = alphanumeric_identifier()
        self.ip_input = ip_ranges
        self.port_input = port_ranges
        self.targets = self._parse_ip_ranges(ip_ranges)
        self.ports = self._parse_port_ranges(port_ranges)
        self.update_cli = update_cli
        self.messenger = messenger
        self.scans = []
        self.scan_results = {}
        self.queue = asyncio.Queue()
        self.start_time = None
        self.semaphore = asyncio.Semaphore(50)

    def _parse_ip_ranges(self, raw):
        hosts = set()
        parts = raw.split(',')

        for part in parts:
            if '/' in part:
                try:
                    net = ipaddress.ip_network(part.strip(), strict=False)
                    hosts.update(str(ip) for ip in net.hosts())
                except ValueError:
                    continue
            elif '-' in part:
                base, end = part.strip().rsplit('.', 1)
                start, stop = map(int, end.split('-'))
                for i in range(start, stop + 1):
                    hosts.add(f"{base}.{i}")
            else:
                hosts.add(part.strip())

        return list(sorted(hosts))

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

    def update_result(self, identifier, result):
        for i, scan in enumerate(self.scans):
            if scan.identifier == identifier:
                self.scans[i] = ScanResult(identifier, scan.address, scan.port, result)
                break
        self.scan_results[identifier] = result
        self.semaphore.release()

    async def _scan_worker(self):
        while True:
            await self.semaphore.acquire()
            ip, port = await self.queue.get()
            identifier = alphanumeric_identifier()
            self.scans.append(ScanResult(identifier, ip, port, None))
            message = InitiateForwarderClientReq(
                forwarder_client_id=identifier,
                ip_address=ip,
                port=port
            )
            await self.messenger.send_message_upstream(message)
            self.queue.task_done()

    async def start(self):
        timestamp = time.strftime('%a, %b %d, %Y at %I:%M:%S %p %Z', time.localtime())
        self.start_time = timestamp
        self.update_cli.display(
            f"Starting scan session {self.identifier} at {timestamp}", 'information'
        )

        for ip in self.targets:
            for port in self.ports:
                await self.queue.put((ip, port))

        workers = [asyncio.create_task(self._scan_worker()) for _ in range(50)]
        await self.queue.join()

        for w in workers:
            w.cancel()

        self.update_cli.display(
            f"Finished scan session {self.identifier}", 'success'
        )