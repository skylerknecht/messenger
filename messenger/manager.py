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
from messenger.text import color_text, bold_text

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
            icon = color_text(icon_label, status_info.color)
        else:
            icon = color_text(status_info.icon, status_info.color)

        print(f'\r{icon} {stdout}')

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

    def __init__(self, server_ip, server_port, ssl, encryption_key):
        """
        Initialize Manager with command definitions, messengers, and prompt session.

        Args:
            server_ip (str): Server IP address for messenger server.
            server_port (int): Port for messenger server.
            ssl (bool): Indicates whether SSL is enabled.
        """
        self.server_commands = {
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
        self.update_cli.display(f'The AES encryption key is {bold_text(self.encryption_key)}', 'Information', reprompt=False)
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
            if i < len(positional_args):
                final_args.append(positional_args[i])
            # else: leave it out; Python will use the function's default or the keyword we set

        # DEBUG: print("DEBUG:", final_args, keyword_args)
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
                    colored_id = color_text(forwarder.identifier, 'cyan')
                elif forwarder.destination_host == '*' and forwarder.destination_port == '*':
                    colored_id = color_text(forwarder.identifier, 'blue')
                else:
                    colored_id = color_text(forwarder.identifier, 'green')

                streaming_clients = [
                    client
                    for client in forwarder.clients
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
        columns = ["Identifier", "Transport", "Status", "Forwarders", "Sent", "Received"]
        if verbose:
            columns.extend(["External IP", "User-Agent"])
        items = []

        for messenger in self.messengers:
            forwarder_ids = [
                color_text(
                    forwarder.identifier,
                    'cyan' if isinstance(forwarder, RemotePortForwarder)
                    else 'blue' if forwarder.destination_host == '*' and forwarder.destination_port == '*'
                    else 'green'
                )
                for forwarder in messenger.forwarders
            ]
            current_messenger_identifier = f"{color_text('>', 'white')} {bold_text(messenger.identifier)}"
            messenger_identifier = bold_text(messenger.identifier)
            identifier = current_messenger_identifier if self.current_messenger == messenger else messenger_identifier
            item = {
                "Identifier": identifier,
                "Transport": messenger.transport_type,
                "Status": messenger.status,
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

        if not identifier:
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
            return

        scanner = next((s for s in scanners if s and s.identifier == identifier), None)
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
            if (result == "closed" or result ==  "•••") and not verbose:
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
                log_dir = os.path.join(os.path.expanduser("~"), ".messenger")
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, "exceptions.log")

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                tb = traceback.format_exc()
                log_entry = (
                    f"[{timestamp}] Unexpected {type(e).__name__}: {e}\n"
                    f"{tb}\n{'-' * 80}\n"
                )

                if self.update_cli.debug_level != 0:
                    self.update_cli.display(log_entry, 'error', reprompt=False)

                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry)
                self.update_cli.display(f'Captured unexpect error and wrote to {log_file}', 'error', reprompt=False)
                self.update_cli.display(f'Please open an issue with the redacted error message at https://github.com/skylerknecht/messenger/issues/new', 'information', reprompt=False)
            except KeyboardInterrupt:
                self.update_cli.display(f"CTRL+C caught, type `exit` to quit Messenger.", 'information',
                                        reprompt=False)
                continue
        await self.exit()

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
          forwarder_config         Format: destination_host:destination_port

        examples:
          remote example.com:9090
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
