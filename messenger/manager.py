import asyncio
import inspect
import sys
import re
import traceback
import time
from collections import namedtuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

from functools import wraps

from messenger.clients.python.builder import build as build_python
from messenger.messengers import Messenger
from messenger.http_ws_server import HTTPWSServer
from messenger.engine import Engine
from messenger.forwarders import LocalPortForwarder, SocksProxy, RemotePortForwarder, InvalidConfigError
from messenger.generator import generate_encryption_key, generate_hash
from messenger.scanner import Scanner

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
        'debug': Status('[DBG]', 'white'),
        'information': Status('[*]', 'cyan'),
        'warning': Status('[!]', 'yellow'),
        'error': Status('[-]', 'red'),
        'success': Status('[+]', 'green'),
        'standard': Status('', 'reset')
    }

    def __init__(self, prompt, session):
        """
        Initializes an UpdateCLI instance with prompt, session, and debug state.

        Args:
            prompt (str): The prompt text to display in the CLI.
            session (PromptSession): The prompt session instance.
        """
        self.prompt = prompt
        self.session = session
        self.debug = False

    def display(self, stdout, status='standard', reprompt=True):
        """
        Display output with a status icon and optionally reprompt.

        Args:
            stdout (str): The output message to display.
            status (str): The status level for the message (e.g., 'debug', 'information', 'warning').
            reprompt (bool): If True, reprompts with the current buffer content.
        """
        status_info = self.STATUS_LEVELS.get(status, self.STATUS_LEVELS['information'])

        if status == 'debug' and not self.debug:
            return

        icon = self.color_text(status_info.icon, status_info.color)
        print(f'\r{icon} {stdout}')

        if reprompt:
            print(f'({self.prompt})~# ' + self.session.app.current_buffer.text, end='')
            sys.stdout.flush()

    @staticmethod
    def color_text(text, color):
        """
        Apply ANSI color codes to text.

        Args:
            text (str): The text to color.
            color (str): The color code to apply.

        Returns:
            str: Colored text.
        """
        colors = {
            'white': '\033[97m',
            'cyan': '\033[96m',
            'yellow': '\033[93m',
            'red': '\033[91m',
            'green': '\033[92m',
            'blue': '\033[94m',
            'reset': '\033[0m'
        }

        return colors.get(color, colors['reset']) + text + colors['reset']

    @staticmethod
    def bold_text(text):
        """
        Returns bolded text using ANSI escape codes.

        Args:
            text (str): The text to bold.

        Returns:
            str: Bolded text.
        """
        return "\033[1m" + text + "\033[0m"


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

    def __init__(self, server_ip, server_port, ssl, encryption_key):
        """
        Initialize Manager with command definitions, messengers, and prompt session.

        Args:
            server_ip (str): Server IP address for messenger server.
            server_port (int): Port for messenger server.
            ssl (bool): Indicates whether SSL is enabled.
        """
        self.server_commands = {
            'build': (self.build, "Builds a messenger client."),
            'forwarders': (self.print_forwarders, "Display a list of forwarders in a table format."),
            'messengers': (self.print_messengers, "Display a list of messengers in a table format."),
            'scans': (self.print_scanners, "Display a list of scanners in a table format."),
            'interact': (self.interact, "Interact with a messenger."),
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
        self.session = PromptSession(completer=DynamicCompleter(self), reserve_space_for_menu=0)
        self.update_cli = UpdateCLI(self.PROMPT, self.session)
        self.encryption_key = encryption_key if encryption_key is not None else generate_encryption_key()
        self.update_cli.display(f'The AES encryption key is {self.update_cli.bold_text(self.encryption_key)}', 'Information', reprompt=False)
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

    async def execute_command(self, command, args):
        """
        Execute a command with optional arguments.

        Args:
            command (str): Command to execute.
            args (list): Arguments for the command.
        """
        if command not in self.commands:
            self.update_cli.display(f'Command `{command}` not found. Type `help` for available commands.', 'warning',
                                    reprompt=False)
            return

        func, _ = self.commands[command]

        if len(args) > 0 and (args[0] == '-h' or args[0] == '--help'):
            docstring = inspect.getdoc(func)
            if not docstring:
                self.update_cli.display(
                    f'Command `{command}` does not have a help message.',
                    'information'
                )
                return
            print(docstring)
            return

        sig = inspect.signature(func)
        params = sig.parameters

        required_params = [p for p in params.values() if p.default == p.empty]

        if len(args) < len(required_params):
            self.update_cli.display(
                f'Command `{command}` requires at least {len(required_params)} argument(s), but received {len(args)}.',
                'warning', reprompt=False
            )
            docstring = inspect.getdoc(func)
            if not docstring:
                self.update_cli.display(
                    f'Command `{command}` does not have a help message.',
                    'information', reprompt=False
                )
                return
            print(docstring)
            return

        call_args = []
        for idx, param in enumerate(params.values()):
            if idx < len(args) and args[idx] != "":
                call_args.append(args[idx])
            elif param.default != param.empty:
                call_args.append(param.default)

        await func(*call_args)

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

    async def build(self, messenger_client_type):
        """
        Interact with a messenger.

        positional arguments:
          messenger_client_type   The type of the Messenger to build.

        examples:
          build python
          build csharp
          build node_js
        """
        if not isinstance(messenger_client_type, str):
            self.update_cli.display(f'Messenger Client Type `{messenger_client_type}` is not valid', 'error', reprompt=False)
            return
        if messenger_client_type.lower() == 'python':
            await build_python()
            return
        elif messenger_client_type.lower() == 'csharp':
            self.update_cli.display(f'Messenger Client Type `{messenger_client_type}` is not implemented', 'error', reprompt=False)
            return
        elif messenger_client_type.lower() == 'node_js':
            self.update_cli.display(f'Messenger Client Type `{messenger_client_type}` is not implemented', 'error', reprompt=False)
            return
        else:
            self.update_cli.display(f'Messenger Client Type `{messenger_client_type}` is not valid', 'error', reprompt=False)
            return

    async def interact(self, messenger):
        """
        Interact with a messenger.

        note:
        Operators can omit the interact command and just provide the Messenger ID to interact with a Messenger.

        positional arguments:
          messenger_id   The ID of the Messenger to interact with.

        examples:
          NkMCyCrrcP
          interact NkMCyCrrcP
        """
        if isinstance(messenger, str):
            for _messenger in self.messengers:
                if messenger == _messenger.identifier:
                    self.current_messenger = _messenger
                    self.update_cli.prompt = self.current_messenger.identifier
                    break
        elif isinstance(messenger, Messenger):
            self.current_messenger = messenger
            self.update_cli.prompt = self.current_messenger.identifier
        else:
            self.update_cli.display(f'Could not find Messenger with ID `{messenger.identifier}`', 'error', reprompt=False)
            return

    async def print_help(self, command=None):
        """
        Display available commands and descriptions.
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

        optional arguments:
          messenger_id       If provided, only displays forwarders for that messenger.

        table columns:
          Type               Type of the forwarder (e.g., "Local Port Forwarder" or "Remote Port Forwarder").
          ID                 Unique identifier for the forwarder instance, color-coded:
                              - Remote forwarders in red.
                              - SOCKS proxies in blue.
                              - Local forwarders in green.
          Clients            Number of clients currently connected to the forwarder.
          Listening Host     Host on which the forwarder is listening for incoming connections.
          Listening Port     Port on which the forwarder is listening for incoming connections.
          Destination Host   Host to which the forwarder relays connections.
          Destination Port   Port to which the forwarder relays connections.

        examples:
          forwarders
          forwarders NkMCyCrrcP
        """
        columns = ["Type", "Identifier", "Clients", "Listening Host", "Listening Port", "Destination Host", "Destination Port"]
        items = []

        if len(self.messengers) == 0:
            self.update_cli.display('There are no connected Messengers, therefore, there cannot be any Forwarders. Idiot.', 'status', reprompt=False)
            return

        if messenger_id and messenger_id not in [messenger.identifier for messenger in self.messengers]:
            self.update_cli.display(f'Messenger ID `{messenger_id}` does not exist.', 'status', reprompt=False)
            return

        for messenger in self.messengers:
            if messenger_id and messenger.identifier != messenger_id:
                continue
            for forwarder in messenger.forwarders:
                # Determine color based on type and configuration
                if isinstance(forwarder, RemotePortForwarder):
                    colored_id = self.update_cli.color_text(forwarder.identifier, 'red')
                elif forwarder.destination_host == '*' and forwarder.destination_port == '*':
                    colored_id = self.update_cli.color_text(forwarder.identifier, 'blue')
                else:
                    colored_id = self.update_cli.color_text(forwarder.identifier, 'green')

                items.append({
                    "Type": forwarder.NAME,
                    "Identifier": colored_id,
                    "Clients": len(forwarder.clients),
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

    async def print_messengers(self, verbose=''):
        """
        Display active messengers in a table format.

        Optional Arguments:
          verbose            Include '-v' or '--verbose' to display additional columns for User-Agent
                             and IP address.

        Table Columns:
          - Identifier:       Unique identifier for the messenger instance.
          - Transport:        Type of transport protocol used by the messenger (e.g., "HTTP" or "WebSocket").
          - Alive:            Connection status, showing "Yes" if the messenger is actively connected, otherwise "No".
          - Forwarders:       Comma-separated list of forwarder IDs associated with the messenger, color-coded:
                                - Remote forwarders in red.
                                - SOCKS proxies in blue.
                                - Local forwarders in green.
          - User-Agent:       (Verbose) User-Agent string of the messenger's connection.
          - IP:               (Verbose) IP address of the messenger's connection.

        Example Usage:
            messengers
            messengers -v
            messengers --verbose
        """
        verbose = '-v' in verbose or '--verbose' in verbose
        columns = ["Identifier", "Transport", "Alive", "Forwarders", "Sent", "Received"]
        if verbose:
            columns.extend(["External IP", "User-Agent"])
        items = []

        for messenger in self.messengers:
            forwarder_ids = [
                self.update_cli.color_text(
                    forwarder.identifier,
                    'red' if isinstance(forwarder, RemotePortForwarder)
                    else 'blue' if forwarder.destination_host == '*' and forwarder.destination_port == '*'
                    else 'green'
                )
                for forwarder in messenger.forwarders
            ]
            current_messenger_identifier = f"{self.update_cli.color_text('>', 'red')} {self.update_cli.bold_text(messenger.identifier)}"
            messenger_identifier = self.update_cli.bold_text(messenger.identifier)
            identifier = current_messenger_identifier if self.current_messenger == messenger else messenger_identifier
            item = {
                "Identifier": identifier,
                "Transport": messenger.transport_type,
                "Alive": "Yes" if messenger.alive else "No",
                "Forwarders": ', '.join(forwarder_ids) if forwarder_ids else '•••',
                "Sent": f"{messenger.format_sent_bytes()}",
                "Received": f"{messenger.format_received_bytes()}"
            }

            if verbose:
                item["External IP"] = messenger.ip if hasattr(messenger, 'ip') else '•••'
                item["User-Agent"] = messenger.user_agent if hasattr(messenger, 'user_agent') else '•••'

            items.append(item)

        if len(items) == 0:
            self.update_cli.display('There are no messengers to display.', 'status', reprompt=False)
            return
        print(self.create_table('Messengers', columns, items))

    async def print_scanners(self, identifier=None, verbose=''):
        """
        Display scan results tracked by the current messenger's scanner.

        Usage:
          scans              → shows a summary of all scan sessions
          scans <identifier> → shows detailed results for a specific scanner
          scans -v           → includes incomplete results (e.g., no reply)

        Without arguments:
          - Displays a summary table of all scan sessions with:
              - Identifier
              - Runtime duration
              - Attempted scans and percentage completion
              - Open and Closed result counts

        With <identifier>:
          - Lists each IP:Port scanned along with the result:
              - open   → port responded successfully
              - closed → port did not respond or was rejected
              - •••    → no response yet (shown only if -v or --verbose is passed)
        """
        verbose = '-v' in verbose or '--verbose' in verbose
        scanners = [scanner for messenger in self.messengers for scanner in messenger.scanners]

        if not scanners:
            self.update_cli.display("There are no scans to display.", 'warning', reprompt=False)
            return

        if identifier:
            scanner = next((s for s in scanners if s and s.identifier == identifier), None)
            if not scanner:
                self.update_cli.display(f"No scanner found with identifier `{identifier}`", 'warning', reprompt=False)
                return

            columns = ["Address", "Port", "Result"]
            items = []

            for scan in scanner.scans.values():
                if scan.result == 0:
                    result = 'open'
                elif scan.result is None:
                    if not verbose:
                        continue
                    result = '•••'
                else:
                    if not verbose:
                        continue
                    result = 'closed'

                items.append({
                    "Address": scan.address,
                    "Port": scan.port,
                    "Result": result
                })

            print(self.create_table('Scans', columns, items))
            return

        columns = ["Identifier", "Runtime", "Attempts", "Progress", "Open", "Closed"]
        items = []

        for scanner in scanners:
            if not hasattr(scanner, 'scans'):
                continue

            open_count = sum(1 for s in scanner.scans.values() if s.result == 0)
            closed_count = sum(1 for s in scanner.scans.values() if s.result not in (0, None))
            attempts = len(scanner.scans)
            runtime = int((scanner.end_time or time.time()) - scanner.start_time)
            hours, minutes = divmod(runtime, 3600)
            minutes, seconds = divmod(minutes, 60)
            formatted_runtime = f"{hours:02}:{minutes:02}:{seconds:02}"

            percent = ((open_count + closed_count) / scanner.total_scans) * 100 if scanner.total_scans else 0
            progress_str = f"{open_count + closed_count}/{scanner.total_scans} ({percent:.0f}%)"

            items.append({
                "Identifier": scanner.identifier,
                "Runtime": formatted_runtime,
                "Attempts": attempts,
                "Progress": progress_str,
                "Open": open_count,
                "Closed": closed_count
            })

        print(self.create_table('Scans', columns, items))

    async def start_command_line_interface(self):
        """
        Start the CLI, display banner, and manage user input.
        """
        await self.messenger_server.start()
        while True:
            try:
                prompt = self.current_messenger.identifier if self.current_messenger else self.PROMPT
                user_input = await self.session.prompt_async(f'({prompt})~# ')
                if not user_input.strip():
                    continue
                user_input = user_input.split(' ')
                command = user_input[0]
                for messenger in self.messengers:
                    if command == messenger.identifier:
                        await self.interact(messenger)
                        break
                else:
                    args = user_input[1:]
                    await self.execute_command(command, args)
            except InvalidConfigError as e:
                self.update_cli.display(str(e), 'error',reprompt=False)
            except Exception as e:
                self.update_cli.display(f"Unexpected {type(e).__name__}:\n{traceback.format_exc()}", 'error',
                                        reprompt=False)
            except KeyboardInterrupt:
                break
        await self.exit()

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

    @require_messenger
    async def start_local_forwarder(self, forwarder_config):
        """
        Start a socks proxy or local forwarder for the currently selected messenger.

        positional arguments:
          forwarder_config   Configuration string for the local forwarder, in one of the following formats:
                               - "192.168.1.10:8080:example.com:9090" : Full configuration with listening and destination details.

        example:
          local 192.168.1.10:8080:example.com:9090
        """
        messenger = self.current_messenger
        if not messenger.alive:
            self.update_cli.display(f'Messenger `{messenger.identifier}` is not alive.', 'error', reprompt=False)
        forwarder = LocalPortForwarder(messenger, forwarder_config, self.update_cli)
        success = await forwarder.start()
        if success:
            messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_remote_forwarder(self, forwarder_config):
        """
        Start a remote forwarder for the currently selected messenger.

        positional arguments:
          forwarder_config   Configuration string for the remote forwarder, in one of the following formats:
                               - "example.com:9090"    : Destination host and port.

        examples:
          remote example.com:9090
        """
        messenger = self.current_messenger
        if not messenger.alive:
            self.update_cli.display(f'Messenger `{messenger.identifier}` is not alive.', 'error', reprompt=False)
        forwarder = RemotePortForwarder(messenger, forwarder_config, self.update_cli)
        await forwarder.start()
        messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_socks_proxy(self, forwarder_config):
        """
        Start a socks proxy for the currently selected messenger.

        positional arguments:
          forwarder_config   Configuration string for the socks proxy, in one of the following formats:
                               - "8080"                               : Listening port only.
                               - "192.168.1.10:8080"                  : Listening host and port.

                             Defaults:
                               - listening_host: "127.0.0.1"

        examples:
          socks 8080
          socks 192.168.1.10:8080
        """
        messenger = self.current_messenger
        if not messenger.alive:
            self.update_cli.display(f'Messenger `{messenger.identifier}` is not alive.', 'error', reprompt=False)
        forwarder = SocksProxy(messenger, forwarder_config, self.update_cli)
        success = await forwarder.start()
        if success:
            messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_scanner(self, ip, port, concurrency=50):
        """
        Start a scan for the given IP ranges and port ranges.

        positional arguments:
          ip           One or more IP addresses, CIDRs, or dash/comma-separated ranges.
          port         One or more ports or port ranges (e.g., 80,443 or 20-25,8080).

        optional arguments:
          concurrency  Maximum number of concurrent scan attempts (default: 50).

        examples:
          scan 192.168.1.10 80
          scan 192.168.1.10-50 80,443
          scan 192.168.1.10,192.168.1.20-30 80-445,1080
          scan 10.0.0.0/24 22-23,80 100
        """
        if not self.current_messenger.alive:
            self.update_cli.display(f'Messenger `{self.current_messenger.identifier}` is not alive.', 'error', reprompt=False)
            return
        try:
            concurrency = int(concurrency)
        except:
            self.update_cli.display(f'{concurrency} is not a valid concurrency.', 'error', reprompt=False)
            return
        scanner = Scanner(ip, port, self.update_cli, self.current_messenger, int(concurrency))
        self.current_messenger.scanners.append(scanner)
        asyncio.create_task(scanner.start())

    async def stop(self, id):
        """
        Stop and remove a forwarder or scanner by ID.

        positional arguments:
          id       ID of the forwarder or scanner to stop and remove.

        examples:
          stop NkMCyCrrcP
        """
        for messenger in self.messengers:
            for forwarder in messenger.forwarders:
                if forwarder.identifier != id:
                    continue
                if isinstance(forwarder, LocalPortForwarder):
                    await forwarder.stop()
                messenger.forwarders.remove(forwarder)
                self.update_cli.display(f'Removed `{id}` from forwarders.', 'information', reprompt=False)
                return
            for scanner in messenger.scanners:
                if scanner.identifier != id:
                    continue
                await scanner.stop()
                return
        self.update_cli.display(f'`{id}` not found', 'error', reprompt=False)


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
        options.extend(messenger.identifier for messenger in self.manager.messengers)
        options.extend(forwarder.identifier for messenger in self.manager.messengers for forwarder in messenger.forwarders)
        options.extend(scanner.identifier for messenger in self.manager.messengers for scanner in messenger.scanners)

        for option in options:
            if option.startswith(word_before_cursor):
                yield Completion(option, start_position=-len(word_before_cursor))
