import ipaddress
import asyncio
from collections import namedtuple
from messenger.generator import alphanumeric_identifier
from messenger.message import InitiateForwarderClientReq

ScanResult = namedtuple("ScanResult", ["identifier", "address", "port", "result"])

class Scanner:
    def __init__(self, subnet_or_ip, ports, update_cli, messenger):
        self.targets = self._expand_targets(subnet_or_ip)
        self.ports = self._parse_ports(ports)
        self.update_cli = update_cli
        self.messenger = messenger
        self.scans = []
        self.scan_results = {}
        self.semaphore = asyncio.Semaphore(50)  # Limit 50 concurrent scans
        self.queue = asyncio.Queue()

    def _expand_targets(self, subnet_or_ip):
        try:
            net = ipaddress.ip_network(subnet_or_ip, strict=False)
            return [str(ip) for ip in net.hosts()]
        except ValueError:
            return [subnet_or_ip]

    def _parse_ports(self, ports):
        if isinstance(ports, int):
            return [ports]
        if isinstance(ports, str):
            return [int(p.strip()) for p in ports.split(',') if p.strip().isdigit()]
        if isinstance(ports, list):
            return [int(p) for p in ports]
        raise ValueError("Ports must be int, str, or list")

    def update_result(self, identifier, result):
        # Called externally when a scan result is received
        for i, scan in enumerate(self.scans):
            if scan.identifier == identifier:
                self.scans[i] = ScanResult(identifier, scan.address, scan.port, result)
                break
        self.scan_results[identifier] = result
        self.semaphore.release()

    async def _scan_worker(self):
        while True:
            ip, port = await self.queue.get()
            identifier = alphanumeric_identifier()
            self.scans.append(ScanResult(identifier, ip, port, None))
            self.messenger.scanners[identifier] = [ip, port]

            await self.semaphore.acquire()
            self.update_cli.display(f'Scanning {ip}:{port}', 'information', reprompt=False)
            message = InitiateForwarderClientReq(
                forwarder_client_id=identifier,
                ip_address=ip,
                port=port
            )
            await self.messenger.send_message_upstream(message)
            self.queue.task_done()

    async def start(self):
        for ip in self.targets:
            for port in self.ports:
                await self.queue.put((ip, port))

        workers = [asyncio.create_task(self._scan_worker()) for _ in range(50)]
        await self.queue.join()
        for w in workers:
            w.cancel()