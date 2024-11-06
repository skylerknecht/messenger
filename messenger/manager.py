import inspect
import sys
import traceback
from collections import namedtuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

from . import BANNER
from messenger.server import Server
from messenger.forwarders import LocalForwarder, RemoteForwarder


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

    def __init__(self, server_ip, server_port, ssl):
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
            'stop': (self.stop, "Stop a forwarder."),
            'help': (self.print_help, "Print a list of commands and their descriptions.")
        }
        self.messengers = []
        self.current_messenger = None
        self.session = PromptSession(completer=DynamicCompleter(self), reserve_space_for_menu=0)
        self.update_cli = UpdateCLI(self.PROMPT, self.session)
        self.messenger_server = Server(self.messengers, self.update_cli, address=server_ip, port=server_port, ssl=ssl)

    @staticmethod
    def create_table(title, columns, items):
        """
        Create a formatted table for display.

        Args:
            title (str): Table title.
            columns (list): Column headers.
            items (list): Rows for the table.

        Returns:
            str: Formatted table string.
        """
        col_widths = [len(col) for col in columns]
        for item in items:
            for idx, col in enumerate(columns):
                col_widths[idx] = max(col_widths[idx], len(str(item.get(col, ''))) + 4)

        header = f"{title:^{sum(col_widths) + len(columns) - 1}}\n"
        header += ' '.join([f"{col:^{width}}" for col, width in zip(columns, col_widths)]) + '\n'
        header += ' '.join(['-' * width for width in col_widths]) + '\n'

        rows = []
        for item in items:
            row = ' '.join([f"{str(item.get(col, '')):^{width}}" for col, width in zip(columns, col_widths)]) + '\n'
            rows.append(row)

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

        Args:
            messenger_id (str or None): ID of a specific messenger (optional).
        """
        columns = ["Type", "ID", "Clients", "Local Host", "Local Port", "Remote Host", "Remote Port"]
        items = []

        for messenger in self.messengers:
            if messenger_id and str(id(messenger)) != messenger_id:
                continue
            for forwarder in messenger.forwarders:
                items.append({
                    "Type": forwarder.name,
                    "ID": id(forwarder),
                    "Clients": len(forwarder.clients),
                    "Local Host": forwarder.local_host,
                    "Local Port": forwarder.local_port,
                    "Remote Host": forwarder.remote_host,
                    "Remote Port": forwarder.remote_port,
                })
        print(self.create_table('Forwarders', columns, items))

    async def print_messengers(self):
        """
        Display messengers in a table format.
        """
        columns = ["ID", "Transport", "Alive", "Forwarders"]
        items = []

        for messenger in self.messengers:
            forwarder_ids = [id(forwarder) for forwarder in messenger.forwarders]
            items.append({
                "ID": id(messenger),
                "Transport": messenger.transport,
                "Alive": messenger.alive,
                "Forwarders": ', '.join(map(str, forwarder_ids)) if forwarder_ids else None,
            })
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
        Start a local forwarder for a specified messenger.

        Args:
            forwarder_config: Configuration for the local forwarder.
            messenger_id (str): ID of the messenger.
        """
        if not messenger_id:
            self.update_cli.display(f'Please provide a Messenger ID.', 'warning', reprompt=False)
            return
        try:
            messenger_id = int(messenger_id)
        except:
            self.update_cli.display(f'\'{messenger_id}\' is not a valid Messenger ID.', 'error', reprompt=False)
            return
        for messenger in self.messengers:
            if id(messenger) != messenger_id:
                continue
            forwarder = LocalForwarder(messenger, forwarder_config, self.update_cli)
            success = await forwarder.start()
            if success:
                messenger.forwarders.append(forwarder)
            return
        self.update_cli.display(f'Messenger \'{messenger_id}\' not found', 'error', reprompt=False)

    async def start_remote_forwarder(self, forwarder_config, messenger_id):
        """
        Start a remote forwarder for a specified messenger.

        Args:
            forwarder_config: Configuration for the remote forwarder.
            messenger_id (str): ID of the messenger.
        """
        if not messenger_id:
            self.update_cli.display(f'Please provide a Messenger ID.', 'warning', reprompt=False)
            return
        try:
            messenger_id = int(messenger_id)
        except:
            self.update_cli.display(f'\'{messenger_id}\' is not a valid Messenger ID.', 'error', reprompt=False)
            return
        for messenger in self.messengers:
            if id(messenger) != messenger_id:
                continue
            forwarder = RemoteForwarder(messenger, forwarder_config, self.update_cli)
            await forwarder.start()
            messenger.forwarders.append(forwarder)
            return
        self.update_cli.display(f'Messenger \'{messenger_id}\' not found', 'error', reprompt=False)

    async def stop(self, forwarder_id):
        """
        Stop and remove a forwarder by ID.

        Args:
            forwarder_id (str): ID of the forwarder.
        """
        for messenger in self.messengers:
            for forwarder in messenger.forwarders:
                if str(id(forwarder)) != forwarder_id:
                    continue
                if isinstance(forwarder, LocalForwarder):
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
        options.extend(str(id(messenger)) for messenger in self.manager.messengers)
        options.extend(str(id(forwarder)) for messenger in self.manager.messengers for forwarder in messenger.forwarders)

        for option in options:
            if option.startswith(word_before_cursor):
                yield Completion(option, start_position=-len(word_before_cursor))
