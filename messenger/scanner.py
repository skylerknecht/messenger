import ipaddress
import asyncio
from messenger.generator import alphanumeric_identifier
from messenger.message import InitiateForwarderClientReq

class Scanner:
    def __init__(self, subnet_or_ip, ports, update_cli, messenger):
        self.targets = self._expand_targets(subnet_or_ip)
        self.ports = self._parse_ports(ports)
        self.messenger = messenger
        self.update_cli = update_cli

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

    async def scan(self, ip, port):
        self.update_cli.display(f'Scanning {ip}:{port}', 'information', reprompt=False)
        identifier = alphanumeric_identifier()
        self.messenger.scanners[identifier] = [ip, port]
        upstream_message = InitiateForwarderClientReq(
            forwarder_client_id=identifier,
            ip_address=ip,
            port=port
        )
        await self.messenger.send_message_upstream(upstream_message)

    async def start(self):
        tasks = [
            asyncio.create_task(self.scan(ip, port))
            for ip in self.targets
            for port in self.ports
        ]
        await asyncio.gather(*tasks)