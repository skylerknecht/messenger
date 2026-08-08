import asyncio
import inspect
import sys
import re
import traceback
import os
from datetime import datetime
from collections import namedtuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

from functools import wraps
from inspect import Parameter

from messenger.messengers import Messenger
from messenger.http_ws_server import HTTPWSServer
from messenger.engine import Engine
from messenger.forwarders import LocalPortForwarder, SocksProxy, RemotePortForwarder, InvalidConfigError
from messenger.generator import generate_encryption_key, generate_hash
from messenger.scanner import Scanner
from messenger.text import color_text, bold_text, strip_ansi
from messenger.logger import Logger

class UpdateCLI:
    """
    A helper class for managing output display and updating the prompt session buffer.

    Attributes:
        prompt (str): The command prompt string.
        session (PromptSession): The prompt session instance for handling CLI input and output.
        debug (bool): If True, enables debug-level messages.
    """
    Status = namedtuple('Status', ['icon', 'color'])

    STATUS_LEVELS = {
        'debug': Status('[DBG {}]', 'white'),
        'information': Status('[*]', 'cyan'),
        'warning': Status('[!]', 'yellow'),
        'error': Status('[-]', 'red'),
        'success': Status('[+]', 'green'),
        'standard': Status('', 'reset')
    }

    def __init__(self, prompt, session, logger, logging_types=None):
        self.prompt = prompt
        self.session = session
        self.logger = logger
        self.debug_types = set()
        self.logging_types = set(logging_types) if logging_types else set()

    def display(self, stdout, status='standard', reprompt=True, debug_level=0):
        status_info = self.STATUS_LEVELS.get(status, self.STATUS_LEVELS['information'])

        if status == 'debug':
            if debug_level not in self.debug_types:
                return
            icon_label = status_info.icon.format(debug_level)
            icon = color_text(icon_label, status_info.color)
        else:
            icon = color_text(status_info.icon, status_info.color)

        timestamp = color_text(f'[{datetime.now().strftime("%H:%M:%S")}]', 'white')
        print(f'\r{timestamp} {icon} {stdout}')

        if reprompt:
            print(f'({self.prompt})~# ' + self.session.app.current_buffer.text, end='')
            sys.stdout.flush()


class Manager:
    """
    Manages CLI commands, server handling, messengers, and dynamic displays.

    Attributes:
        commands (dict): Available commands with methods and descriptions.
        messengers (list): List of current messenger instances.
        current_messenger (str or None): ID of the active messenger.
        session (PromptSession): The prompt session for CLI input.
        update_cli (UpdateCLI): For display handling.
        messenger_server (Server): Server instance for managing messenger connections.
    """

    PROMPT = 'messenger'

    def __init__(self, server_ip, server_port, ssl, encryption_key, config_dir=None, logging_types=None, config_path=None, created_dir=False, created_config=False, quiet=False):
        """
        Initialize Manager with command definitions, messengers, and prompt session.

        Args:
            server_ip (str): Server IP address for messenger server.
            server_port (int): Port for messenger server.
            ssl (bool): Indicates whether SSL is enabled.
        """
        self.server_commands = {
            'debug': (self.debug, "Toggle debug output by type."),
            'logging': (self.logging, "Toggle message logging by type."),
            'forwarders': (self.print_forwarders, "Display a list of forwarders in a table format."),
            'messengers': (self.print_messengers, "Display a list of messengers in a table format."),
            'scans': (self.print_scanners, "Display a list of scanners in a table format."),
            'interact': (self.interact, "Interact with a messenger."),
            'rename': (self.rename, "Rename a messenger, forwarder, or scanner."),
            'stop': (self.stop, "Stop a forwarder or a scanner."),
            'help': (self.print_help, "Display this help message."),
            '?': (self.print_help, "Display this help message but with fewer characters."),
            'exit': (self.exit, "Exit Messenger, stopping the server."),
        }
        self.messenger_commands = {
            'back': (self.back, "Return to the main menu."),
            'local': (self.start_local_forwarder, "Start a local forwarder."),
            'remote': (self.start_remote_forwarder, "Start a remote forwarder."),
            'socks': (self.start_socks_proxy, "Start a socks proxy."),
            'portscan': (self.start_scanner, "Scan for open ports."),
        }
        self.commands = {**self.server_commands, **self.messenger_commands}
        self.messengers = []
        self.current_messenger = None
        self.logger = Logger(config_dir)
        self.session = PromptSession(completer=DynamicCompleter(self), reserve_space_for_menu=0)
        self.update_cli = UpdateCLI(self.PROMPT, self.session, self.logger, logging_types)
        self.encryption_key = encryption_key if encryption_key is not None else generate_encryption_key()
        if not quiet:
            self.update_cli.display(f'The AES encryption key is {bold_text(self.encryption_key)}', 'information', reprompt=False)
            if created_dir:
                self.update_cli.display(f'Created messenger directory: {self.logger.base_dir}', 'information', reprompt=False)
            if created_config:
                self.update_cli.display(f'Created config file: {config_path}', 'information', reprompt=False)
            if self.logger.logs_created:
                self.update_cli.display(f'Created logging directory: {self.logger.log_dir}', 'information', reprompt=False)
            self.update_cli.display(f'Using messenger directory: {self.logger.base_dir}', 'information', reprompt=False)
            self.update_cli.display(f'Using config file: {config_path}', 'information', reprompt=False)
            self.update_cli.display(f'Using logging directory: {self.logger.log_dir}', 'information', reprompt=False)
        self.messenger_engine = Engine(self.messengers, self.update_cli, generate_hash(self.encryption_key))
        self.messenger_server = HTTPWSServer(self.update_cli, self.messenger_engine, ip=server_ip, port=server_port, ssl=ssl)

    @staticmethod
    def strip_ansi_codes(text):
        """
        Remove ANSI color codes from a string.

        Args:
            text (str): Text that may contain ANSI color codes.

        Returns:
            str: Text without ANSI color codes.
        """
        ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
        return ansi_escape.sub('', text)

    @staticmethod
    def create_table(title, columns, items):
        """
        Create a formatted table for display with proper centering, even with color codes.

        Args:
            title (str): Table title.
            columns (list): Column headers.
            items (list): Rows for the table.

        Returns:
            str: Formatted table string.
        """
        # Prepare items without ANSI codes for calculating column widths
        items_no_ansi = []
        for item in items:
            item_no_ansi = {col: Manager.strip_ansi_codes(str(item.get(col, ''))) for col in columns}
            items_no_ansi.append(item_no_ansi)

        # Calculate column widths based on the items without ANSI codes
        col_widths = [len(col) for col in columns]
        for item in items_no_ansi:
            for idx, col in enumerate(columns):
                col_widths[idx] = max(col_widths[idx], len(item.get(col, '')) + 4)  # Padding for readability

        # Create table header
        header = f"{title:^{sum(col_widths) + len(columns) - 1}}\n"
        header += ' '.join([f"{col:^{width}}" for col, width in zip(columns, col_widths)]) + '\n'
        header += ' '.join(['-' * width for width in col_widths]) + '\n'

        # Use the original items list with ANSI codes for the final output
        rows = []
        for item in items:
            row_parts = []
            for col, width in zip(columns, col_widths):
                cell_value = str(item.get(col, ''))
                stripped_value = Manager.strip_ansi_codes(cell_value)
                # Calculate padding needed based on stripped text length
                padding = (width - len(stripped_value)) // 2
                padded_value = ' ' * padding + cell_value + ' ' * (width - len(stripped_value) - padding)
                row_parts.append(padded_value)
            rows.append(' '.join(row_parts) + '\n')

        table = header + ''.join(rows)
        return table

    async def execute_command(self, command, tokens):
        if command not in self.commands:
            self.update_cli.display(f'Command `{command}` not found. Type `help` for available commands.', 'warning',
                                    reprompt=False)
            return

        func, _ = self.commands[command]

        if '-h' in tokens or '--help' in tokens:
            docstring = inspect.getdoc(func)
            print(docstring or f'Command `{command}` does not have a help message.')
            return

        sig = inspect.signature(func)
        params = sig.parameters

        positional_args = []
        keyword_args = {}
        consumed_flags = set()

        output_path = None
        tokens_iter = iter(tokens)
        for token in tokens_iter:
            if token in ('-o', '--output'):
                try:
                    output_path = next(tokens_iter)
                except StopIteration:
                    self.update_cli.display(f'Flag `{token}` requires a file path.', 'error', reprompt=False)
                    return
            elif token.startswith('--') or token.startswith('-'):
                name = token.lstrip('-').replace('-', '_')
                param = params.get(name)
                if param is None or param.kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY):
                    self.update_cli.display(f'{command} does not support the flag `{token}`.', 'error', reprompt=False)
                    return
                consumed_flags.add(name)
                default = param.default
                if isinstance(default, bool):
                    keyword_args[name] = not default
                else:
                    try:
                        keyword_args[name] = next(tokens_iter)
                    except StopIteration:
                        self.update_cli.display(f'Flag `{token}` requires a value.', 'error', reprompt=False)
                        return
            else:
                positional_args.append(token)

        # Params that can take positionals (exclude self and any provided via flags)
        bindable_params = [
            p for p in params.values()
            if p.name != 'self' and p.name not in consumed_flags
        ]

        # Count required params (no defaults) among bindables
        required_params = [
            p for p in bindable_params
            if p.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
               and p.default == Parameter.empty
        ]
        if len(positional_args) < len(required_params):
            self.update_cli.display(
                f'Command `{command}` requires {len(required_params)} argument(s), but got {len(positional_args)}.',
                'warning', reprompt=False
            )
            return

        # Map ONLY provided positionals; DO NOT append defaults positionally
        final_args = []
        for i, param in enumerate(bindable_params):
            if param.kind == Parameter.VAR_POSITIONAL:
                final_args.extend(positional_args[i:])
                break
            if i < len(positional_args):
                final_args.append(positional_args[i])

        # DEBUG: print("DEBUG:", final_args, keyword_args)
        await func(*final_args, **keyword_args)
        return output_path

    def require_messenger(func):
        """Decorator to ensure a messenger is selected before executing the command."""

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not self.current_messenger:
                self.update_cli.display("Please interact with a messenger before using this command.", 'error',
                                        reprompt=False)
                return
            return await func(self, *args, **kwargs)

        return wrapper

    @staticmethod
    async def exit():
        """
        Exit the application, stopping the messenger server.
        """
        print('\rMessenger Server stopped.')
        sys.exit(0)

    async def back(self):
        """
        Return to the main menu.
        """
        self.current_messenger = None

    async def debug(self, types=None):
        """
        Enable debug output by type. With no arguments, show current status.

        Type | Scope                           | Description
        -----|---------------------------------|---------------------------------------------------------
        0    | None                            | Disable all debug output
        1    | Handler Messages                | Handler received/sent messages
        2    | Messenger Messages              | Messenger received/sent messages
        3    | TCP Clients Messages      | TCP clients received/sent messages
        4    | Handler Data                    | Handler received/sent raw data
        5    | Messenger Data                  | Messenger received/sent raw data
        6    | TCP Clients Data          | TCP clients received/sent raw data

        optional:
          types        Comma-separated list of types to toggle (e.g. 1,4)

        examples:
          debug
          debug 0
          debug 1,4
          debug 2,5
        """
        VALID_TYPES = {1, 2, 3, 4, 5, 6}
        LABELS = {
            1: 'Handler Messages',
            2: 'Messenger Messages',
            3: 'TCP Clients Messages',
            4: 'Handler Data',
            5: 'Messenger Data',
            6: 'TCP Clients Data',
        }
        if types is None:
            if not self.update_cli.debug_types:
                self.update_cli.display('All debug output disabled.', 'information', reprompt=False)
            else:
                for t in sorted(VALID_TYPES):
                    state = color_text('on', 'green') if t in self.update_cli.debug_types else color_text('off', 'red')
                    self.update_cli.display(f'{t} {LABELS[t]}: {state}', 'standard', reprompt=False)
            return

        raw = str(types).split(',')
        parsed = set()
        for token in raw:
            token = token.strip()
            try:
                val = int(token)
            except ValueError:
                self.update_cli.display(f'`{token}` is not a valid debug type.', 'error', reprompt=False)
                return
            if val == 0:
                self.update_cli.debug_types.clear()
                self.update_cli.display('All debug output disabled.', 'success', reprompt=False)
                return
            if val not in VALID_TYPES:
                self.update_cli.display(f'`{val}` is not a valid debug type. Valid types: 1-6.', 'error', reprompt=False)
                return
            parsed.add(val)

        for t in parsed:
            if t in self.update_cli.debug_types:
                self.update_cli.debug_types.discard(t)
                self.update_cli.display(f'{LABELS[t]} disabled.', 'information', reprompt=False)
            else:
                self.update_cli.debug_types.add(t)
                self.update_cli.display(f'{LABELS[t]} enabled.', 'information', reprompt=False)

    async def logging(self, types=None):
        """
        Toggle which message types are logged to disk. With no arguments, show current status.
        All types are enabled by default.

        Type | Message Type
        -----|----------------------------------
        0    | Disable all logging
        1    | CheckInMessage
        2    | InitiateTCPClientReq
        3    | InitiateTCPClientRep
        4    | SendDataMessage
        5    | InitiateBINDReq
        6    | InitiateBINDRep

        optional:
          types        Comma-separated list of types to toggle (e.g. 1,4)

        examples:
          logging
          logging 0
          logging 1
          logging 2,3
        """
        VALID_TYPES = {1, 2, 3, 4, 5, 6}
        LABELS = {
            1: 'CheckInMessage',
            2: 'InitiateTCPClientReq',
            3: 'InitiateTCPClientRep',
            4: 'SendDataMessage',
            5: 'InitiateBINDReq',
            6: 'InitiateBINDRep',
        }
        if types is None:
            if not self.update_cli.logging_types:
                self.update_cli.display('All message logging disabled.', 'information', reprompt=False)
            else:
                for t in sorted(VALID_TYPES):
                    state = color_text('on', 'green') if t in self.update_cli.logging_types else color_text('off', 'red')
                    self.update_cli.display(f'{t} {LABELS[t]}: {state}', 'standard', reprompt=False)
            return

        raw = str(types).split(',')
        parsed = set()
        for token in raw:
            token = token.strip()
            try:
                val = int(token)
            except ValueError:
                self.update_cli.display(f'`{token}` is not a valid logging type.', 'error', reprompt=False)
                return
            if val == 0:
                self.update_cli.logging_types.clear()
                self.update_cli.display('All message logging disabled.', 'success', reprompt=False)
                return
            if val not in VALID_TYPES:
                self.update_cli.display(f'`{val}` is not a valid logging type. Valid types: 1-4.', 'error', reprompt=False)
                return
            parsed.add(val)

        for t in parsed:
            if t in self.update_cli.logging_types:
                self.update_cli.logging_types.discard(t)
                self.update_cli.display(f'{LABELS[t]} logging disabled.', 'information', reprompt=False)
            else:
                self.update_cli.logging_types.add(t)
                self.update_cli.display(f'{LABELS[t]} logging enabled.', 'information', reprompt=False)

    async def interact(self, messenger):
        """
        Interact with a messenger.

        required:
          messenger                The ID or Messenger object to interact with.

        examples:
          interact NkMCyCrrcP
          NkMCyCrrcP
        """

        if isinstance(messenger, str):
            for _messenger in self.messengers:
                if messenger in (_messenger.identifier, _messenger.nickname):
                    self.current_messenger = _messenger
                    self.update_cli.prompt = self.current_messenger.nickname
                    return
            self.update_cli.display(f'Could not find Messenger `{messenger}`', 'error',
                                    reprompt=False)
            return
        elif isinstance(messenger, Messenger):
            self.current_messenger = messenger
            self.update_cli.prompt = self.current_messenger.nickname
        else:
            self.update_cli.display(f'Could not find Messenger `{messenger.nickname}`', 'error', reprompt=False)
            return

    async def print_help(self, command=None):
        """
        Display help message.

        optional:
          command                  Specific command to show detailed help for.

        examples:
          help
          help forwarders
        """
        if command and command in self.commands:
            func = self.commands[command][0]
            docstring = inspect.getdoc(func)
            if not docstring:
                self.update_cli.display(
                    f'Command `{command}` does not have a help message.',
                    'information', reprompt=False
                )
                return
            print(docstring)
            return
        print("Server commands:")
        for command, (func, description) in self.server_commands.items():
            print(f"  {command:10} {description}")
        print()
        print("Messenger commands (must be interacting with a messenger):")
        for command, (func, description) in self.messenger_commands.items():
            print(f"  {command:10} {description}")

    async def print_forwarders(self, messenger_id=None):
        """
        Display active forwarders in a table format.

        optional:
          messenger_id             Filter by Messenger ID.

        examples:
          forwarders
          forwarders NkMCyCrrcP
        """
        columns = ["Type", "Name", "Clients", "Listening Host", "Listening Port", "Destination Host", "Destination Port"]
        items = []

        if len(self.messengers) == 0:
            self.update_cli.display('There are no connected Messengers, therefore, there cannot be any Forwarders. Idiot.', 'status', reprompt=False)
            return

        if messenger_id and not any(messenger_id in (m.identifier, m.nickname) for m in self.messengers):
            self.update_cli.display(f'Messenger `{messenger_id}` does not exist.', 'status', reprompt=False)
            return

        for messenger in self.messengers:
            if messenger_id and messenger_id not in (messenger.identifier, messenger.nickname):
                continue
            for forwarder in messenger.forwarders:
                if isinstance(forwarder, RemotePortForwarder):
                    colored_id = color_text(forwarder.nickname, 'cyan')
                elif forwarder.destination_host == '*' and forwarder.destination_port == '*':
                    colored_id = color_text(forwarder.nickname, 'blue')
                else:
                    colored_id = color_text(forwarder.nickname, 'green')

                streaming_clients = [
                    client
                    for client in forwarder.clients
                ]

                items.append({
                    "Type": forwarder.NAME,
                    "Name": colored_id,
                    "Clients": len(streaming_clients),
                    "Listening Host": forwarder.listening_host,
                    "Listening Port": forwarder.listening_port,
                    "Destination Host": forwarder.destination_host,
                    "Destination Port": forwarder.destination_port,
                })
        if len(items) == 0:
            if messenger_id:
                self.update_cli.display(f'There are no forwarders to display for messenger `{messenger_id}`.', 'status', reprompt=False)
            else:
                self.update_cli.display('There are no forwarders to display.', 'status', reprompt=False)
            return
        print(self.create_table('Forwarders', columns, items))

    async def print_messengers(self, *identifiers):
        """
        Display active messengers. With no arguments, show a summary table.
        With one or more IDs or names, show detailed information.

        optional:
          identifiers              IDs or names of messengers to show details for.

        examples:
          messengers
          messengers NkMCyCrrcP
          messengers dc01 dc02
        """
        if identifiers:
            for identifier in identifiers:
                messenger = None
                for m in self.messengers:
                    if identifier in (m.identifier, m.nickname):
                        messenger = m
                        break
                if not messenger:
                    self.update_cli.display(f'Messenger `{identifier}` not found.', 'error', reprompt=False)
                    continue
                self._print_messenger_detail(messenger)
            return

        columns = ["Name", "Transport", "Status", "IPs", "Forwarders / Scanners", "Sent", "Received"]
        items = []

        for messenger in self.messengers:
            forwarder_ids = [
                color_text(
                    forwarder.nickname,
                    'cyan' if isinstance(forwarder, RemotePortForwarder)
                    else 'blue' if forwarder.destination_host == '*' and forwarder.destination_port == '*'
                    else 'green'
                )
                for forwarder in messenger.forwarders
            ]
            scanner_ids = [
                color_text(scanner.nickname, 'yellow')
                for scanner in messenger.scanners
            ]
            all_ids = forwarder_ids + scanner_ids
            current_messenger_name = f"{color_text('>', 'white')} {bold_text(messenger.nickname)}"
            messenger_name = bold_text(messenger.nickname)
            name = current_messenger_name if self.current_messenger == messenger else messenger_name
            item = {
                "Name": name,
                "Transport": messenger.transport_type,
                "Status": messenger.status,
                "IPs": ', '.join(sorted(messenger.ips)) if messenger.ips else '•••',
                "Forwarders / Scanners": ', '.join(all_ids) if all_ids else '•••',
                "Sent": f"{messenger.format_sent_bytes()}",
                "Received": f"{messenger.format_received_bytes()}"
            }
            items.append(item)

        if len(items) == 0:
            self.update_cli.display('There are no messengers to display.', 'status', reprompt=False)
            return
        print(self.create_table('Messengers', columns, items))

    def _print_messenger_detail(self, messenger):
        from datetime import datetime as dt, timezone
        header = f"Messenger ({messenger.identifier})"
        if messenger._nickname:
            header += f" ({messenger._nickname})"
        separator = '-' * len(header)
        first_seen = dt.fromtimestamp(messenger.first_seen, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        last_seen = dt.fromtimestamp(messenger.last_check_in, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        ua = messenger.user_agent if hasattr(messenger, 'user_agent') else '•••'
        ips = ', '.join(sorted(messenger.ips)) if messenger.ips else '•••'

        lines = [
            header,
            separator,
            f"  Transport:   {messenger.transport_type}",
            f"  Status:      {messenger.status}",
            f"  IPs:         {ips}",
            f"  First Seen:  {first_seen}",
            f"  Last Seen:   {last_seen}",
            f"  Sent:        {messenger.format_sent_bytes()}",
            f"  Received:    {messenger.format_received_bytes()}",
            f"  User-Agent:  {ua}",
        ]

        if messenger.forwarders:
            lines.append(f"  Forwarders:")
            for f in messenger.forwarders:
                if isinstance(f, RemotePortForwarder):
                    ftype = "Remote"
                    cfg = f"{f.listening_host}:{f.listening_port} -> {f.destination_host}:{f.destination_port}"
                elif f.destination_host == '*' and f.destination_port == '*':
                    ftype = "Socks"
                    cfg = f"{f.listening_host}:{f.listening_port} -> *:*"
                else:
                    ftype = "Local"
                    cfg = f"{f.listening_host}:{f.listening_port} -> {f.destination_host}:{f.destination_port}"
                lines.append(f"    {f.nickname} ({ftype}) {cfg}")
        else:
            lines.append(f"  Forwarders:  •••")

        if messenger.scanners:
            lines.append(f"  Scanners:")
            for s in messenger.scanners:
                cfg = s.ip_input
                if s.port_input:
                    cfg += f" {s.port_input}"
                else:
                    cfg += f" top {len(s.ports)}"
                lines.append(f"    {s.nickname} ({cfg}) — {s.progress_str} {s.open_count} open {s.closed_count} closed")
        else:
            lines.append(f"  Scanners:    •••")

        print('\n'.join(lines))

    async def print_scanners(self, identifier=None, show_closed=False):
        """
        Display scan results.

        optional:
          identifier               Specific scanner ID to show detailed scan results.
          --show-closed            Include closed and pending results (default: False).

        examples:
          scans
          scans NkMCyCrrcP
          scans NkMCyCrrcP --show-closed
        """
        scanners = [scanner for messenger in self.messengers for scanner in messenger.scanners]

        if not scanners:
            self.update_cli.display("There are no scans to display.", 'warning', reprompt=False)
            return

        if not identifier:
            columns = ["Messenger", "Scanner", "Runtime", "Attempts", "Progress", "Open", "Closed"]
            items = []

            for scanner in scanners:
                if not hasattr(scanner, 'scans'):
                    continue

                items.append({
                    "Messenger": scanner.messenger.nickname,
                    "Scanner": scanner.nickname,
                    "Runtime": scanner.formatted_runtime,
                    "Attempts": scanner.attempts,
                    "Progress": scanner.progress_str,
                    "Open": scanner.open_count,
                    "Closed": scanner.closed_count
                })

            print(self.create_table('Scans', columns, items))
            return

        scanner = next((s for s in scanners if s and identifier in (s.identifier, s.nickname)), None)
        if not scanner:
            self.update_cli.display(f"No scanner found with identifier `{identifier}`", 'warning', reprompt=False)
            return

        columns = ["Address", "Port", "Result"]
        items = []

        for scan in scanner.scans.values():
            result = "•••"
            if scan.result == 0:
                result = "open"
            elif isinstance(scan.result, int):
                result = "closed"
            if (result == "closed" or result == "•••") and not show_closed:
                continue

            items.append({
                "Address": scan.address,
                "Port": scan.port,
                "Result": result
            })

        print(self.create_table(f"Scanner {identifier} Results", columns, items))

    async def start_command_line_interface(self):
        """
        Start the CLI, display banner, and manage user input.
        """
        await self.messenger_server.start()

        while True:
            try:
                prompt = self.current_messenger.nickname if self.current_messenger else self.PROMPT
                user_input = await self.session.prompt_async(f'({prompt})~# ')
            except KeyboardInterrupt:
                self.update_cli.display(f"CTRL+C caught, type `exit` to quit Messenger.", 'information',
                                        reprompt=False)
                continue

            if not user_input.strip():
                continue

            timestamp = self.logger.now()
            output_path = None
            with self.logger.capture() as output:
                try:
                    parts = user_input.split(' ')
                    command = parts[0]
                    for messenger in self.messengers:
                        if command in (messenger.identifier, messenger.nickname):
                            await self.interact(messenger)
                            break
                    else:
                        output_path = await self.execute_command(command, parts[1:])
                except InvalidConfigError as e:
                    self.update_cli.display(str(e), 'error', reprompt=False)
                except KeyboardInterrupt:
                    self.update_cli.display(f"CTRL+C caught, type `exit` to quit Messenger.", 'information',
                                            reprompt=False)
                except Exception as e:
                    self._log_unexpected_error(e)

            captured = strip_ansi(output.getvalue()).strip()
            self.logger.record_command(timestamp, user_input.strip(), captured)

            if output_path:
                self._write_output_file(output_path, captured)
        await self.exit()

    def _write_output_file(self, path, contents):
        try:
            path = os.path.expanduser(path)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(contents + '\n')
            self.update_cli.display(f'Output written to {path}.', 'success', reprompt=False)
        except OSError as e:
            self.update_cli.display(f'Could not write output to {path}: {e}', 'error', reprompt=False)

    def _log_unexpected_error(self, e):
        log_file = os.path.join(self.logger.base_dir, "exceptions.log")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb = traceback.format_exc()
        log_entry = (
            f"[{timestamp}] Unexpected {type(e).__name__}: {e}\n"
            f"{tb}\n{'-' * 80}\n"
        )

        if self.update_cli.debug_types:
            self.update_cli.display(log_entry, 'error', reprompt=False)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
        self.update_cli.display(f'Captured unexpected error and wrote to {log_file}', 'error', reprompt=False)
        self.update_cli.display(f'Please open an issue with the redacted error message at https://github.com/skylerknecht/messenger/issues/new', 'information', reprompt=False)

    @require_messenger
    async def start_local_forwarder(self, forwarder_config):
        """
        Start a local forwarder.

        required:
          forwarder_config         Format: listening_host:listening_port:destination_host:destination_port

        examples:
          local 127.0.0.1:8080:example.com:9090
        """
        messenger = self.current_messenger
        forwarder = LocalPortForwarder(messenger, forwarder_config, self.update_cli)
        success = await forwarder.start()
        if success:
            messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_remote_forwarder(self, forwarder_config):
        """
        Start a remote forwarder.

        required:
          forwarder_config         Format: listening_host:listening_port:destination_host:destination_port

        examples:
          remote 0.0.0.0:8080:127.0.0.1:80
        """
        messenger = self.current_messenger
        forwarder = RemotePortForwarder(messenger, forwarder_config, self.update_cli)
        await forwarder.start()
        messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_socks_proxy(self, forwarder_config):
        """
        Start a SOCKS proxy.

        required:
          forwarder_config         Format: [listening_host:]listening_port

        examples:
          socks 9050
          socks 127.0.0.1:9050
        """
        messenger = self.current_messenger
        forwarder = SocksProxy(messenger, forwarder_config, self.update_cli)
        success = await forwarder.start()
        if success:
            messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_scanner(self, ips, ports=None, concurrency=50, top_ports=100):
        """
        Start a scan against IPs and ports.

        required:
          ips                      IPs, CIDRs, or ranges to scan.

        optional:
          ports                    Specific ports/ranges to scan (e.g., 80,443 or 1-1024).
          --concurrency            Max concurrent scan attempts (default: 50).
          --top-ports              Use top N ports if ports not specified (default: 100).

        examples:
          portscan 192.168.1.10
          portscan 10.0.0.0/24 --top-ports 1000 --concurrency 100
        """
        try:
            concurrency = int(concurrency)
        except:
            self.update_cli.display(f'{concurrency} is not a valid concurrency.', 'error', reprompt=False)
            return
        try:
            top_ports = int(top_ports)
        except:
            self.update_cli.display(f'{top_ports} is not a valid integer.', 'error', reprompt=False)
            return

        scanner = Scanner(ips, ports, int(top_ports), self.update_cli, self.current_messenger, int(concurrency))
        self.current_messenger.scanners.append(scanner)
        asyncio.create_task(scanner.start())

    async def stop(self, id):
        """
        Stop a forwarder or scanner by ID.

        required:
          id                       ID of the forwarder or scanner to stop.

        examples:
          stop NkMCyCrrcP
        """
        for messenger in self.messengers:
            for forwarder in messenger.forwarders:
                if id not in (forwarder.identifier, forwarder.nickname):
                    continue
                await forwarder.stop()
                messenger.forwarders.remove(forwarder)
                self.update_cli.display(f'Removed `{forwarder.nickname}` from forwarders.', 'information', reprompt=False)
                return
            for scanner in messenger.scanners:
                if id not in (scanner.identifier, scanner.nickname):
                    continue
                await scanner.stop()
                return
        self.update_cli.display(f'`{id}` not found', 'error', reprompt=False)

    async def rename(self, id, name):
        """
        Rename a messenger, forwarder, or scanner.

        required:
          id                       ID or current name of the target.
          name                     The new name to assign.

        examples:
          rename NkMCyCrrcP dc01
          rename dc01 webserver
        """
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            self.update_cli.display('Names may only contain letters, numbers, hyphens, and underscores.', 'error', reprompt=False)
            return

        all_objects = list(self.messengers)
        for messenger in self.messengers:
            all_objects.extend(messenger.forwarders)
            all_objects.extend(messenger.scanners)

        target = None
        for obj in all_objects:
            if id in (obj.identifier, obj.nickname):
                target = obj
                break

        if not target:
            self.update_cli.display(f'`{id}` not found.', 'error', reprompt=False)
            return

        for obj in all_objects:
            if obj is not target and name in (obj.identifier, obj._nickname):
                self.update_cli.display(f'Name `{name}` is already in use.', 'error', reprompt=False)
                return

        old = target.nickname
        target.nickname = name
        if self.current_messenger and self.current_messenger is target:
            self.update_cli.prompt = name
        self.update_cli.display(f'`{old}` is now known as `{name}`.', 'success', reprompt=False)


class DynamicCompleter(Completer):
    """
    Custom Completer class for dynamic command and messenger completion.

    Methods:
        get_completions(document, complete_event): Generates completion options for CLI.
    """

    def __init__(self, manager):
        """
        Initialize DynamicCompleter with manager for access to command options.

        Args:
            manager (Manager): Instance of Manager for command options.
        """
        self.manager = manager

    def get_completions(self, document, complete_event):
        """
        Generate completion options based on available commands and messenger IDs.

        Args:
            document (Document): The current document containing input text.
            complete_event (CompleteEvent): The event that triggered completion.

        Yields:
            Completion: Each possible completion option.
        """
        word_before_cursor = document.get_word_before_cursor()
        options = list(self.manager.commands.keys())
        for messenger in self.manager.messengers:
            options.append(messenger.nickname)
            for forwarder in messenger.forwarders:
                options.append(forwarder.nickname)
            for scanner in messenger.scanners:
                options.append(scanner.nickname)

        for option in options:
            if option.startswith(word_before_cursor):
                yield Completion(option, start_position=-len(word_before_cursor))
