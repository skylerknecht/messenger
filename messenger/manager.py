import inspect
import sys
import re
import traceback
from collections import namedtuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

from messenger.server import Server
from messenger.forwarders import LocalPortForwarder, RemotePortForwarder


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
            print(self.prompt + self.session.app.current_buffer.text, end='')
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

    PROMPT = '(messenger)~# '

    def __init__(self, server_ip, server_port, ssl, encryption_key):
        """
        Initialize Manager with command definitions, messengers, and prompt session.

        Args:
            server_ip (str): Server IP address for messenger server.
            server_port (int): Port for messenger server.
            ssl (bool): Indicates whether SSL is enabled.
        """
        self.commands = {
            'exit': (self.exit, "Exit the application, stopping the messenger server."),
            'forwarders': (self.print_forwarders, "Display a list of active forwarders in a table format."),
            'messengers': (self.print_messengers, "Display a list of messengers in a table format."),
            'local': (self.start_local_forwarder, "Start a local forwarder for the specified messenger."),
            'remote': (self.start_remote_forwarder, "Start a remote forwarder."),
            'socks': (self.start_local_forwarder, "Start a socks proxy."),
            'stop': (self.stop, "Stop a forwarder."),
            'help': (self.print_help, "Print a list of commands and their descriptions.")
        }
        self.messengers = []
        self.current_messenger = None
        self.session = PromptSession(completer=DynamicCompleter(self), reserve_space_for_menu=0)
        self.update_cli = UpdateCLI(self.PROMPT, self.session)
        self.messenger_server = Server(self.messengers, self.update_cli, address=server_ip, port=server_port, ssl=ssl, encryption_key=encryption_key)

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
            self.update_cli.display(f'Command "{command}" not found. Type "help" for available commands.', 'warning',
                                    reprompt=False)
            return

        func, _ = self.commands[command]

        if len(args) > 0 and (args[0] == '-h' or args[0] == '--help'):
            docstring = inspect.getdoc(func)
            print(docstring)
            return

        sig = inspect.signature(func)
        params = sig.parameters

        required_params = [p for p in params.values() if p.default == p.empty]
        optional_params = [p for p in params.values() if p.default != p.empty]

        if len(args) < len(required_params):
            self.update_cli.display(
                f'Command "{command}" requires at least {len(required_params)} argument(s), but received {len(args)}.',
                'warning', reprompt=False
            )
            docstring = inspect.getdoc(func)
            print(docstring)
            return

        call_args = []
        for idx, param in enumerate(params.values()):
            if idx < len(args):
                call_args.append(args[idx])
            elif param.default != param.empty:
                call_args.append(param.default)

        await func(*call_args)

    @staticmethod
    async def exit():
        """
        Exit the application, stopping the messenger server.
        """
        print('\rMessenger Server stopped.')
        sys.exit(0)

    async def print_help(self, command=None):
        """
        Display available commands and descriptions.
        """
        if command and command in self.commands:
            func = self.commands[command][0]
            docstring = inspect.getdoc(func)
            print(docstring)
            return
        print("Available commands:")
        for command, (func, description) in self.commands.items():
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
          forwarders 4369562880
        """
        columns = ["Type", "Identifier", "Clients", "Listening Host", "Listening Port", "Destination Host", "Destination Port"]
        items = []

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
                    "Type": forwarder.name,
                    "Identifier": colored_id,
                    "Clients": len(forwarder.clients),
                    "Listening Host": forwarder.listening_host,
                    "Listening Port": forwarder.listening_port,
                    "Destination Host": forwarder.destination_host,
                    "Destination Port": forwarder.destination_port,
                })
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
        columns = ["Identifier", "Transport", "Alive", "Forwarders"]
        if verbose:
            columns.extend(["User-Agent", "IP"])
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
            item = {
                "Identifier": messenger.identifier,
                "Transport": messenger.transport,
                "Alive": "Yes" if messenger.alive else "No",
                "Forwarders": ', '.join(forwarder_ids) if forwarder_ids else '•••',
            }

            if verbose:
                item["User-Agent"] = messenger.user_agent if hasattr(messenger, 'user_agent') else '•••'
                item["IP"] = messenger.ip if hasattr(messenger, 'ip') else '•••'

            items.append(item)

        print(self.create_table('Messengers', columns, items))

    async def start_command_line_interface(self):
        """
        Start the CLI, display banner, and manage user input.
        """
        await self.messenger_server.start()
        while True:
            try:
                prompt = self.current_messenger if self.current_messenger else self.PROMPT
                user_input = await self.session.prompt_async(prompt)
                if not user_input.strip():
                    continue
                user_input = user_input.split(' ')
                command = user_input[0]
                args = user_input[1:]
                await self.execute_command(command, args)
            except Exception as e:
                self.update_cli.display(f"Unexpected {type(e).__name__}:\n{traceback.format_exc()}", 'error',
                                        reprompt=False)
            except KeyboardInterrupt:
                break
        await self.exit()

    async def start_local_forwarder(self, forwarder_config, messenger_id):
        """
        Start a socks proxy or local forwarder for a specified messenger.

        positional arguments:
          forwarder_config   Configuration string for the local forwarder, in one of the following formats:
                               - "8080"                               : Listening port only.
                               - "192.168.1.10:8080"                  : Listening host and port.
                               - "192.168.1.10:8080:example.com:9090" : Full configuration with listening and destination details.

                             Defaults:
                               - listening_host: "127.0.0.1"
                               - destination_host: "*"
                               - destination_port: "*"

          messenger_id       ID of the messenger to which this forwarder will be attached.

        examples:
          socks 8080 4369562880
          socks 192.168.1.10:8080
          local 192.168.1.10:8080:example.com:9090
        """
        if not messenger_id:
            self.update_cli.display(f'Please provide a Messenger ID.', 'warning', reprompt=False)
            return
        for messenger in self.messengers:
            if messenger.identifier != messenger_id or not messenger.alive:
                continue
            forwarder = LocalPortForwarder(messenger, forwarder_config, self.update_cli)
            success = await forwarder.start()
            if success:
                messenger.forwarders.append(forwarder)
            return
        self.update_cli.display(f'Messenger \'{messenger_id}\' not found or is not alive.', 'error', reprompt=False)

    async def start_remote_forwarder(self, forwarder_config, messenger_id):
        """
        Start a remote forwarder for a specified messenger.

        positional arguments:
          forwarder_config   Configuration string for the remote forwarder, in one of the following formats:
                               - "9090"                : Destination port only.
                               - "example.com:9090"    : Destination host and port.

                             Defaults:
                               - destination_host: "127.0.0.1" if only a port is provided.

          messenger_id       ID of the messenger to which this forwarder will be attached.

        examples:
          remote 9090 4369562880
          remote example.com:9090 4369562880
        """
        if not messenger_id:
            self.update_cli.display(f'Please provide a Messenger ID.', 'warning', reprompt=False)
            return
        for messenger in self.messengers:
            if messenger.identifier != messenger_id or not messenger.alive:
                continue
            forwarder = RemotePortForwarder(messenger, forwarder_config, self.update_cli)
            await forwarder.start()
            messenger.forwarders.append(forwarder)
            return
        self.update_cli.display(f'Messenger \'{messenger_id}\' not found or is not alive.', 'error', reprompt=False)

    async def stop(self, forwarder_id):
        """
        Stop and remove a forwarder by ID.

        positional arguments:
          forwarder_id       ID of the forwarder to stop and remove.

        examples:
          stop 4369562880
        """
        for messenger in self.messengers:
            for forwarder in messenger.forwarders:
                if forwarder.identifier != forwarder_id:
                    continue
                if isinstance(forwarder, LocalPortForwarder):
                    await forwarder.stop()
                messenger.forwarders.remove(forwarder)
                self.update_cli.display(f'Removed \'{forwarder_id}\' from forwarders.', 'information', reprompt=False)
                return
        self.update_cli.display(f'Forwarder \'{forwarder_id}\' not found', 'error', reprompt=False)


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

        for option in options:
            if option.startswith(word_before_cursor):
                yield Completion(option, start_position=-len(word_before_cursor))
