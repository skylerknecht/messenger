import asyncio
import inspect
import sys
import re
import traceback
from collections import namedtuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

from functools import wraps
from inspect import Parameter

try:
    from messenger.clients.python.builder import build as build_python
    imported_python_client = True
except ImportError:
    imported_python_client = False
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
        'debug': Status('[DBG {}]', 'white'),
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
        self.debug_level = 0

    def display(self, stdout, status='standard', reprompt=True, debug_level=0):
        status_info = self.STATUS_LEVELS.get(status, self.STATUS_LEVELS['information'])

        if status == 'debug':
            if self.debug_level < debug_level:
                return
            icon_label = status_info.icon.format(debug_level)
            icon = self.color_text(icon_label, status_info.color)
        else:
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
            'debug': (self.debug, "Set the debug level."),
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
        tokens_iter = iter(tokens)

        for token in tokens_iter:
            if token.startswith('--') or token.startswith('-'):
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

        required_params = [
            p for p in params.values()
            if p.name != 'self'
               and p.name not in consumed_flags
               and p.kind not in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
               and p.default == Parameter.empty
        ]

        if len(positional_args) < len(required_params):
            self.update_cli.display(
                f'Command `{command}` requires {len(required_params)} argument(s), but got {len(positional_args)}.',
                'warning', reprompt=False
            )
            return

        final_args = []
        for i, param in enumerate(params.values()):
            if param.name in consumed_flags or param.name == 'self':
                continue
            if i < len(positional_args):
                final_args.append(positional_args[i])
            elif param.default != Parameter.empty:
                final_args.append(param.default)

        await func(*final_args, **keyword_args)

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

    async def debug(self, level: int):
        """
        Set the debug level for CLI output.

        Debug Level | Scope                           | Description
        ------------|---------------------------------|---------------------------------------------------------
        0           | None                            | No debug output
        1           | Handler Messages                | Handler received/sent messages
        2           | Messenger Messages              | Messenger received/sent messages
        3           | Forwarder Clients Messages      | Forwarder clients received/sent messages
        4           | Handler Data                    | Handler received/sent raw data
        5           | Messenger Data                  | Messenger received/sent raw data
        6           | Forwarder Clients Data          | Forwarder clients received/sent raw data

        required:
          level        The numeric debug level

        examples:
          debug 0
        """
        try:
            level = int(level)
        except ValueError:
            self.update_cli.display("Debug level must be an integer.", "error", reprompt=False)
            return

        self.update_cli.debug_level = level
        self.update_cli.display(f"Debug level set to {level}.", "success", reprompt=False)

    async def build(self, messenger_client_type, no_obfuscate=False, name="messenger-client"):
        """
         Build a messenger client.

         required:
           messenger_client_type   The type of the Messenger to build (e.g., python, csharp, node_js).

         optional:
           --no-obfuscate           Disable obfuscation of the messenger client (default: False).
           --name                   Name of the output client (default: messenger-client).

         examples:
           build python
           build csharp --no-obfuscate --name custom-client
         """
        if not isinstance(messenger_client_type, str):
            self.update_cli.display(f'Messenger Client Type `{messenger_client_type}` is not valid', 'error', reprompt=False)
            return
        if messenger_client_type.lower() == 'python':
            if not imported_python_client:
                self.update_cli.display(f'Messenger Client Type `{messenger_client_type}` is not available, try `{sys.argv[0]} --update-submodules`', 'error',
                                        reprompt=False)
                return
            await build_python(no_obfuscate, name)
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

        required:
          messenger                The ID or Messenger object to interact with.

        examples:
          interact NkMCyCrrcP
          NkMCyCrrcP
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
        Display help message.

        optional:
          command                  Specific command to show detailed help for.

        examples:
          help
          help build
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

                streaming_clients = [
                    client
                    for client in forwarder.clients
                    if client.streaming
                ]

                items.append({
                    "Type": forwarder.NAME,
                    "Identifier": colored_id,
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

    async def print_messengers(self, verbose=False):
        """
        Display active messengers in a table format.

        optional:
          --verbose, -v            Show additional columns for User-Agent and IP address (default: False).

        examples:
          messengers
          messengers --verbose
        """
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

    async def print_scanners(self, identifier=None, verbose=False):
        """
        Display scan results.

        optional:
          identifier               Specific scanner ID to show detailed scan results.
          --verbose, -v            Include incomplete/no-response results (default: False).

        examples:
          scans
          scans NkMCyCrrcP
          scans --verbose
        """
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

        columns = ["Messenger", "Scanner", "Runtime", "Attempts", "Progress", "Open", "Closed"]
        items = []

        for scanner in scanners:
            if not hasattr(scanner, 'scans'):
                continue

            items.append({
                "Messenger": scanner.messenger.identifier,
                "Scanner": scanner.identifier,
                "Runtime": scanner.formatted_runtime,
                "Attempts": scanner.attempts,
                "Progress": scanner.progress_str,
                "Open": scanner.open_count,
                "Closed": scanner.closed_count
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
                self.update_cli.display(f"CTRL+C caught, type `exit` to quit Messenger.", 'information',
                                        reprompt=False)
                continue
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
        Start a local forwarder.

        required:
          forwarder_config         Format: listening_host:port:destination_host:port

        examples:
          local 127.0.0.1:8080:example.com:9090
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
        Start a remote forwarder.

        required:
          forwarder_config         Format: destination_host:port

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
        Start a SOCKS proxy.

        required:
          forwarder_config         Format: [listening_host:]port

        examples:
          socks 8080
          socks 127.0.0.1:8080
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
        if not self.current_messenger.alive:
            self.update_cli.display(f'Messenger `{self.current_messenger.identifier}` is not alive.', 'error', reprompt=False)
            return
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
