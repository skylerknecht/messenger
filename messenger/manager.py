import asyncio
import errno
import inspect
import signal
import sys
import re
import os
from datetime import datetime, timezone
from collections import namedtuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.patch_stdout import patch_stdout

from functools import wraps
from inspect import Parameter

from messenger.messengers import Messenger, HTTPMessenger
from messenger.http_ws_server import HTTPWSServer
from messenger.engine import Engine
from messenger.forwarders import LocalPortForwarder, SocksProxy, RemotePortForwarder, InvalidConfigError
from messenger.message import CheckOutMessage
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
        self.reset_display_filters()
        self.logging_types = set(logging_types) if logging_types else set()

    def reset_display_filters(self):
        self.display_filters = {'handlers': {'disabled': {'warning'}}}

    def display(self, stdout, status='standard', reprompt=True, display_module=None):
        status_info = self.STATUS_LEVELS.get(status, self.STATUS_LEVELS['information'])

        if status == 'debug':
            if not self.display_filters.get(display_module, {}).get('debug', False):
                return
            icon_label = status_info.icon.format(display_module)
            icon = color_text(icon_label, status_info.color)
        elif display_module and display_module in self.display_filters:
            if status in self.display_filters[display_module].get('disabled', set()):
                return
            icon = color_text(status_info.icon, status_info.color)
        else:
            icon = color_text(status_info.icon, status_info.color)

        print(f'{icon} {stdout}')

    def log_unexpected_error(self, e):
        log_file = self.logger.log_exception(e)
        self.display(f'Caught unexpected error, logged to {log_file}', 'error', reprompt=False)
        self.display(
            'Please open an issue with the redacted error at '
            'https://github.com/skylerknecht/messenger/issues/new',
            'information', reprompt=False
        )


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

    TYPE_LABELS = {
        "SOCKS Server": "SOCKS",
        "Local Port Forwarder": "LPF",
        "Remote Port Forwarder": "RPF",
    }

    STATE_COLORS = {
        'running': 'cyan',
        'stopped': 'yellow',
        'completed': 'green',
    }

    @staticmethod
    def _format_timestamp(ts):
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    @staticmethod
    def _color_forwarder(forwarder):
        if isinstance(forwarder, RemotePortForwarder):
            return color_text(forwarder.nickname, 'cyan')
        if forwarder.destination_host == '*' and forwarder.destination_port == '*':
            return color_text(forwarder.nickname, 'blue')
        return color_text(forwarder.nickname, 'green')

    def __init__(self, server_ip, server_port, ssl, encryption_key, config_dir=None, logging_types=None, config_path=None, created_dir=False, created_config=False, quiet=False):
        """
        Initialize Manager with command definitions, messengers, and prompt session.

        Args:
            server_ip (str): Server IP address for messenger server.
            server_port (int): Port for messenger server.
            ssl (bool): Indicates whether SSL is enabled.
        """
        self.server_commands = {
            'display': (self.display_settings, "Change display levels."),
            'logging': (self.logging, "Toggle message logging by type."),
            'forwarders': (self.print_forwarders, "Display a list of forwarders in a table format."),
            'messengers': (self.print_messengers, "Display a list of messengers in a table format."),
            'scans': (self.print_scanners, "Display a list of scanners in a table format."),
            'interact': (self.interact, "Interact with a messenger."),
            'rename': (self.rename, "Rename a messenger, forwarder, or scanner."),
            'stop': (self.stop, "Stop a forwarder or a scanner."),
            'kill': (self.kill, "Kill a messenger."),
            'adaptative': (self.adaptative, "Turn adaptive polling on and off."),
            'watch': (self.watch, "Watch a table with live updates."),
            'help': (self.print_help, "Display this help message."),
            '?': (self.print_help, "Display this help message but with fewer characters."),
            'exit': (self.exit, "Exit Messenger, stopping the server."),
        }
        self.messenger_commands = {
            'back': (self.back, "Return to the main menu."),
            'local': (self.start_local_forwarder, "Start a local port forwarder."),
            'remote': (self.start_remote_forwarder, "Start a remote port forwarder."),
            'socks': (self.start_socks_proxy, "Start a SOCKS server."),
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
            if logging_types:
                msg_names = ', '.join(sorted({
                    {1: 'CheckInMessage', 2: 'InitiateTCPClientReq', 3: 'InitiateTCPClientRep',
                     4: 'SendDataMessage', 5: 'InitiateBINDReq', 6: 'InitiateBINDRep',
                     7: 'CheckOutMessage'}[t]
                    for t in logging_types if t in range(1, 8)
                }))
                self.update_cli.display(
                    f'Logging commands and {msg_names} messages to: {self.logger.log_dir}',
                    'information', reprompt=False)
            else:
                self.update_cli.display(
                    f'Logging commands and no messages to: {self.logger.log_dir}',
                    'information', reprompt=False)
        self._watching = None
        self._watch_interval = 1
        self._previous_sigint = None
        self.messenger_engine = Engine(self.messengers, self.update_cli, generate_hash(self.encryption_key))
        self.messenger_server = HTTPWSServer(self.update_cli, self.messenger_engine, ip=server_ip, port=server_port, ssl_cert=ssl)

    @staticmethod
    def _truncate_list(csv_str, max_items=3):
        items = [i.strip() for i in csv_str.split(',')]
        if len(items) <= max_items:
            return ', '.join(items)
        return ', '.join(items[:max_items]) + f', +{len(items) - max_items} more'

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
            if self.current_messenger.checked_out:
                self.update_cli.display(f"Messenger `{self.current_messenger.nickname}` is killed.", 'error',
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

    async def display_settings(self, module=None, type_name=None):
        """
        Toggle message types globally or for an individual profile.

        Type      | Description
        ----------|-----------------------------------
        debug     | Toggle debug messages
        success       | Toggle success messages
        warning       | Toggle warning messages
        info          | Toggle info messages
        error         | Toggle error messages

        optional:
          module                   handlers, messengers, forwarders, or scanners
          type_name                Comma-separated types to toggle

        examples:
          display                          Show all module status
          display off                      Turn off messages for all profiles
          display reset                    Restore startup defaults
          display debug                    Toggle debug for all modules
          display success                  Toggle success messages globally
          display warning,error            Toggle warnings and errors globally
          display info                     Toggle info messages globally
          display handlers                 Show handler status
          display handlers debug           Toggle handler debug
          display handlers debug,warning   Toggle handler debug and warnings
          display messengers error         Toggle messenger errors
          display scanners info            Toggle scanner progress messages
        """
        MODULES = ('handlers', 'messengers', 'forwarders', 'scanners')
        STATUS_TYPES = ('warning', 'success', 'information', 'error')
        STATUS_MAP = {
            'debug': 'debug',
            'warning': 'warning',
            'warnings': 'warning',
            'success': 'success',
            'successes': 'success',
            'informational': 'information',
            'information': 'information',
            'info': 'information',
            'infos': 'information',
            'error': 'error',
            'errors': 'error',
        }
        VALID_TYPES = set(STATUS_MAP)

        def format_toggle(enabled):
            return color_text('on', 'green') if enabled else color_text('off', 'red')

        def toggle(modules, names):
            for status in dict.fromkeys(STATUS_MAP[name] for name in names):
                if status == 'debug':
                    enabled = not all(self.update_cli.display_filters.get(mod, {}).get('debug', False)
                                      for mod in modules)
                else:
                    enabled = not all(status not in self.update_cli.display_filters.get(mod, {}).get('disabled', set())
                                      for mod in modules)
                for mod in modules:
                    filt = self.update_cli.display_filters.setdefault(mod, {})
                    if status == 'debug':
                        filt['debug'] = enabled
                    elif enabled:
                        filt.setdefault('disabled', set()).discard(status)
                    else:
                        filt.setdefault('disabled', set()).add(status)

        def show_table(modules):
            columns = ['Module', 'Debug', 'Warnings', 'Successes', 'Infos', 'Errors']
            items = []
            for mod in modules:
                filt = self.update_cli.display_filters.get(mod, {})
                items.append({
                    'Module': mod,
                    'Debug': format_toggle(filt.get('debug', False)),
                    'Warnings': format_toggle('warning' not in filt.get('disabled', set())),
                    'Successes': format_toggle('success' not in filt.get('disabled', set())),
                    'Infos': format_toggle('information' not in filt.get('disabled', set())),
                    'Errors': format_toggle('error' not in filt.get('disabled', set())),
                })
            print(self.create_table('Display', columns, items))

        if module is None:
            show_table(MODULES)
            return

        if module in ('off', 'reset'):
            if type_name is not None:
                self.update_cli.display(f'`display {module}` does not take another argument.', 'error', reprompt=False)
                return
            if module == 'reset':
                self.update_cli.reset_display_filters()
            else:
                self.update_cli.display_filters = {
                    mod: {'debug': False, 'disabled': set(STATUS_TYPES)} for mod in MODULES
                }
            show_table(MODULES)
            return

        if module not in MODULES:
            if type_name is not None:
                self.update_cli.display(f'`{module}` is not a valid profile.', 'error', reprompt=False)
                return
            global_types = [t.strip() for t in module.split(',')]
            if all(t in VALID_TYPES for t in global_types):
                toggle(MODULES, global_types)
                show_table(MODULES)
                return
            self.update_cli.display(
                f'`{module}` is not a valid module or type.', 'error', reprompt=False
            )
            return

        if type_name is None:
            show_table((module,))
            return

        types = [t.strip() for t in type_name.split(',')]
        for t in types:
            if t not in VALID_TYPES:
                self.update_cli.display(
                    f'`{t}` is not a valid type. Valid types: {", ".join(sorted(VALID_TYPES))}.', 'error', reprompt=False
                )
                return

        toggle((module,), types)
        show_table((module,))

    async def logging(self, types=None):
        """
        Toggle which message types are logged to disk. With no arguments, show current status.

        Type | Message Type
        -----|----------------------------------
        0    | Disable all logging
        1    | CheckInMessage
        2    | InitiateTCPClientReq
        3    | InitiateTCPClientRep
        4    | SendDataMessage
        5    | InitiateBINDReq
        6    | InitiateBINDRep
        7    | CheckOutMessage

        optional:
          types        Comma-separated list of types to toggle (e.g. 1,4), or 0 to disable all

        examples:
          logging
          logging 0
          logging 1
          logging 2,3
        """
        VALID_TYPES = {1, 2, 3, 4, 5, 6, 7}
        LABELS = {
            1: 'CheckInMessage',
            2: 'InitiateTCPClientReq',
            3: 'InitiateTCPClientRep',
            4: 'SendDataMessage',
            5: 'InitiateBINDReq',
            6: 'InitiateBINDRep',
            7: 'CheckOutMessage',
        }
        if types is None:
            items = [
                {'Type': t, 'Message': LABELS[t],
                 'Logging': color_text('on', 'green') if t in self.update_cli.logging_types else color_text('off', 'red')}
                for t in sorted(VALID_TYPES)
            ]
            print(self.create_table('Logging', ['Type', 'Message', 'Logging'], items))
            return

        if str(types).strip() == '0':
            self.update_cli.logging_types.clear()
            self.update_cli.display('All message logging disabled.', 'success', reprompt=False)
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
            if val not in VALID_TYPES:
                self.update_cli.display(f'`{val}` is not a valid logging type. Valid types: 1-7.', 'error', reprompt=False)
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

        if isinstance(messenger, Messenger):
            self.current_messenger = messenger
            self.update_cli.prompt = self.current_messenger.nickname
            return
        resolved = self._resolve_messenger(messenger)
        if not resolved:
            return
        self.current_messenger = resolved
        self.update_cli.prompt = self.current_messenger.nickname

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

    async def print_forwarders(self, identifier=None):
        """
        Display active forwarders. With no arguments, show a summary table.
        With an ID or name, show detailed information for that forwarder
        or filter by messenger.

        optional:
          identifier               ID or name of a forwarder or messenger.
          -o, --output             Write output to a file.

        examples:
          forwarders
          forwarders NkMCyCrrcP
        """
        if len(self.messengers) == 0:
            self.update_cli.display('There are no connected Messengers, therefore, there cannot be any Forwarders.', 'information', reprompt=False)
            return

        if identifier == 'all':
            for messenger in self.messengers:
                for forwarder in messenger.forwarders:
                    self._print_forwarder_detail(messenger, forwarder)
            return

        if identifier:
            for messenger in self.messengers:
                for forwarder in messenger.forwarders:
                    if identifier in (forwarder.identifier, forwarder.nickname):
                        self._print_forwarder_detail(messenger, forwarder)
                        return

        columns = ["Type", "Messenger", "Name", "Configuration", "Clients"]
        items = []

        if identifier and not any(identifier in (m.identifier, m.nickname) for m in self.messengers):
            self.update_cli.display(f'`{identifier}` not found.', 'error', reprompt=False)
            return

        for messenger in self.messengers:
            if identifier and identifier not in (messenger.identifier, messenger.nickname):
                continue
            for forwarder in messenger.forwarders:
                orphan = isinstance(forwarder, RemotePortForwarder) and forwarder.is_orphan
                listen = f'{forwarder.listening_host}:{forwarder.listening_port}'
                dest = 'None' if orphan else f'{forwarder.destination_host}:{forwarder.destination_port}'
                config = f'({listen}) -> ({dest})'

                items.append({
                    "Type": self.TYPE_LABELS.get(forwarder.NAME, forwarder.NAME),
                    "Messenger": messenger.nickname,
                    "Name": self._color_forwarder(forwarder),
                    "Configuration": config,
                    "Clients": len(forwarder.clients),
                })
        if len(items) == 0:
            if identifier:
                self.update_cli.display(f'There are no forwarders to display for messenger `{identifier}`.', 'information', reprompt=False)
            else:
                self.update_cli.display('There are no forwarders to display.', 'information', reprompt=False)
            return
        print(self.create_table('Forwarders', columns, items))

    async def print_messengers(self, *identifiers):
        """
        Display active messengers. With no arguments, show a summary table.
        With one or more IDs or names, show detailed information.

        optional:
          identifiers              IDs or names of messengers to show details for.
          -o, --output             Write output to a file.

        examples:
          messengers
          messengers NkMCyCrrcP
          messengers dc01 dc02
        """
        if identifiers:
            if identifiers == ('all',):
                for messenger in self.messengers:
                    self._print_messenger_detail(messenger)
                return
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

        columns = ["Name", "Transport", "Status", "IPs", "Forwarders", "Sent", "Received"]
        items = []

        for messenger in self.messengers:
            forwarder_ids = [self._color_forwarder(f) for f in messenger.forwarders]
            current_messenger_name = f"{color_text('>', 'white')} {bold_text(messenger.nickname)}"
            messenger_name = bold_text(messenger.nickname)
            name = current_messenger_name if self.current_messenger == messenger else messenger_name
            item = {
                "Name": name,
                "Transport": messenger.transport_type,
                "Status": messenger.status,
                "IPs": ', '.join(sorted(messenger.ips)) if messenger.ips else 'None',
                "Forwarders": ', '.join(forwarder_ids) if forwarder_ids else 'None',
                "Sent": f"{messenger.format_sent_bytes()}",
                "Received": f"{messenger.format_received_bytes()}"
            }
            items.append(item)

        if len(items) == 0:
            self.update_cli.display('There are no messengers to display.', 'information', reprompt=False)
            return
        print(self.create_table('Messengers', columns, items))

    def _print_messenger_detail(self, messenger):
        header = f"Messenger ({messenger.identifier})"
        if messenger._nickname:
            header += f" ({messenger._nickname})"
        separator = '-' * len(header)
        ua = messenger.user_agent if hasattr(messenger, 'user_agent') else 'None'
        ips = ', '.join(sorted(messenger.ips)) if messenger.ips else 'None'

        lines = [
            header,
            separator,
            f"Transport:   {messenger.transport_type}",
            f"Status:      {messenger.status}",
            f"IPs:         {ips}",
            f"First Seen:  {self._format_timestamp(messenger.first_seen)}",
            f"Last Seen:   {self._format_timestamp(messenger.last_check_in)}",
            f"Sent:        {messenger.format_sent_bytes()}",
            f"Received:    {messenger.format_received_bytes()}",
            f"User-Agent:  {ua}",
        ]
        if isinstance(messenger, HTTPMessenger):
            lines.append(f"Adaptive:    {'on' if messenger.adaptative else 'off'}")

        if messenger.forwarders:
            lines.append(f"Forwarders:")
            for f in messenger.forwarders:
                label = self.TYPE_LABELS.get(f.NAME, f.NAME)
                lines.append(f"  {f.nickname}")
                lines.append(f"    Type:     {label}")
                lines.append(f"    Config:   {f._endpoint_str()}")
                lines.append(f"    Clients:  {len(f.clients)}")
        else:
            lines.append(f"Forwarders:  None")

        if messenger.scanners:
            lines.append(f"Scanners:")
            for s in messenger.scanners:
                ips = s.ip_input
                ports = s.port_input if s.port_input else f"top {len(s.ports)}"
                progress = s.open_count + s.closed_count
                percent = int((progress / s.total_scans) * 100) if s.total_scans else 0
                lines.append(f"  {s.nickname}")
                lines.append(f"    IPs:          {ips}")
                lines.append(f"    Ports:        {ports}")
                lines.append(f"    Concurrency:  {s.concurrency}")
                lines.append(f"    Progress:     {percent}%")
                lines.append(f"    Open:         {s.open_count}")
                lines.append(f"    Closed:       {s.closed_count}")
        else:
            lines.append(f"Scanners:    None")

        print('\n'.join(lines))

    def _print_forwarder_detail(self, messenger, forwarder):
        header = f"Forwarder ({forwarder.identifier})"
        if forwarder._nickname:
            header += f" ({forwarder._nickname})"
        separator = '-' * len(header)

        lines = [
            header,
            separator,
            f"Type:       {forwarder.NAME}",
            f"Messenger:  {messenger.nickname}",
            f"Config:     {forwarder._endpoint_str()}",
            f"Clients:    {len(forwarder.clients)}",
            f"Created:    {self._format_timestamp(forwarder.created)}",
        ]

        print('\n'.join(lines))

    def _print_scanner_detail(self, scanner, open=False, show_all_results=False):
        header = f"Scan ({scanner.identifier})"
        if scanner._nickname:
            header += f" ({scanner._nickname})"
        separator = '-' * len(header)
        ips = scanner.ip_input
        ports = scanner.port_input if scanner.port_input else f"top {len(scanner.ports)}"
        state = scanner.state
        started = self._format_timestamp(scanner.start_time)
        completed = self._format_timestamp(scanner.end_time) if scanner.end_time else 'None'

        print(header)
        print(separator)
        print(f"Messenger:    {scanner.messenger.nickname}")
        print(f"IPs:          {ips}")
        print(f"Ports:        {ports}")
        print(f"State:        {color_text(state, self.STATE_COLORS[state])}")
        print(f"Started:      {started}")
        print(f"Completed:    {completed}")
        print(f"Runtime:      {scanner.formatted_runtime}")
        print(f"Concurrency:  {scanner.concurrency}")
        print(f"Progress:     {scanner.progress_str}")
        print(f"Open:         {scanner.open_count}")
        print(f"Closed:       {scanner.closed_count}")
        print()

        columns = ["Address", "Port", "Result"]
        items = []

        for scan in scanner.scans.values():
            result = "None"
            if scan.result == 0:
                result = "open"
            elif isinstance(scan.result, int):
                result = "closed"
            if open and result != "open":
                continue

            items.append({
                "Address": scan.address,
                "Port": scan.port,
                "Result": result
            })

        if not items:
            return

        limit = 40
        truncated = not show_all_results and len(items) > limit
        display_items = items[:limit] if truncated else items

        print(self.create_table('Results', columns, display_items))

        if truncated:
            self.update_cli.display(
                f'Showing {limit} of {len(items)} results. Use --show-all-results to display all and --open to only show open results.',
                'information', reprompt=False
            )

    async def print_scanners(self, identifier=None, open=False, show_all_results=False):
        """
        Display scan results.

        optional:
          identifier               Specific scanner ID to show detailed scan results.
          --open                   Only show open results (default: False).
          --show-all-results       Show all results instead of the top 40 (default: False).
          -o, --output             Write output to a file.

        examples:
          scans
          scans NkMCyCrrcP
          scans NkMCyCrrcP --open
          scans NkMCyCrrcP --show-all-results
        """
        scanners = [scanner for messenger in self.messengers for scanner in messenger.scanners]

        if not scanners:
            self.update_cli.display("There are no scans to display.", 'warning', reprompt=False)
            return

        if not identifier:
            columns = ["Messenger", "Scanner", "State", "Runtime", "Concurrency", "Progress", "Open", "Closed"]
            items = []

            for scanner in scanners:
                if not hasattr(scanner, 'scans'):
                    continue

                state = scanner.state
                items.append({
                    "Messenger": scanner.messenger.nickname,
                    "Scanner": scanner.nickname,
                    "State": color_text(state, self.STATE_COLORS[state]),
                    "Runtime": scanner.formatted_runtime,
                    "Concurrency": scanner.concurrency,
                    "Progress": scanner.progress_str,
                    "Open": scanner.open_count,
                    "Closed": scanner.closed_count,
                })

            print(self.create_table('Scans', columns, items))
            return

        if identifier == 'all':
            for scanner in scanners:
                self._print_scanner_detail(scanner, open, show_all_results)
            return

        scanner = next((s for s in scanners if s and identifier in (s.identifier, s.nickname)), None)
        if not scanner:
            self.update_cli.display(f"No scanner found with identifier `{identifier}`", 'warning', reprompt=False)
            return

        self._print_scanner_detail(scanner, open, show_all_results)

    def _asyncio_exception_handler(self, loop, context):
        """Log every asyncio-signaled exception as a warning through the CLI."""
        exc = context.get('exception')
        detail = f'{type(exc).__name__}: {exc}' if exc else context.get('message', 'unknown')
        self.update_cli.display(
            f'asyncio: {detail}',
            'warning', reprompt=False, display_module='handlers'
        )
        if isinstance(exc, OSError) and exc.errno in (errno.EMFILE, errno.ENFILE):
            worst = None
            for messenger in self.messengers:
                for forwarder in messenger.forwarders:
                    if worst is None or len(forwarder.clients) > len(worst[1].clients):
                        worst = (messenger, forwarder)
            if worst:
                m, f = worst
                self.update_cli.display(
                    f'File descriptors exhausted. Forwarder `{f.nickname}` on '
                    f'messenger `{m.nickname}` has the most clients ({len(f.clients)}).',
                    'error', reprompt=False, display_module='forwarders'
                )

    def _handle_watch_sigint(self, signum=None, frame=None):
        self._watching = None
        if self._previous_sigint is not None:
            signal.signal(signal.SIGINT, self._previous_sigint)
            self._previous_sigint = None
            self.session.output.quit_alternate_screen()
            self.session.output.flush()

    async def watch(self, target='messengers', interval=1):
        """
        Watch a table with live updates. Press Ctrl+C to stop.

        optional:
          target                   Table to watch: messengers, forwarders, or scans (default: messengers).
          --interval               Refresh interval in whole seconds (default: 1).

        examples:
          watch
          watch forwarders
          watch scans
          watch messengers --interval 2
        """
        targets = {
            'messengers': self.print_messengers,
            'forwarders': self.print_forwarders,
            'scans': self.print_scanners,
        }
        render = targets.get(target)
        if not render:
            self.update_cli.display(
                f'Unknown watch target `{target}`. Use messengers, forwarders, or scans.',
                'error', reprompt=False
            )
            return
        try:
            interval = int(str(interval))
        except ValueError:
            self.update_cli.display('Interval must be a whole number of seconds.', 'error', reprompt=False)
            return
        if interval < 1:
            self.update_cli.display('Interval must be at least 1 second.', 'error', reprompt=False)
            return
        if self._watching is not None:
            self._handle_watch_sigint()
            return

        self._previous_sigint = signal.signal(signal.SIGINT, self._handle_watch_sigint)
        self._watching = render
        self._watch_interval = interval
        self.session.output.enter_alternate_screen()
        self.session.output.flush()
        self.update_cli.display(f'Watching {target} table.', 'information', reprompt=False)

    async def start_command_line_interface(self):
        """
        Start the CLI, display banner, and manage user input.
        """
        asyncio.get_running_loop().set_exception_handler(self._asyncio_exception_handler)
        await self.messenger_server.start()

        with patch_stdout(raw=True):
            while True:
                try:
                    render = self._watching
                    if render is not None:
                        try:
                            sys.stdout.write('\033[2J\033[H')
                            await render()
                            print('\nPress Ctrl+C to exit.')
                            sys.stdout.flush()
                            await asyncio.sleep(self._watch_interval)
                        except BaseException:
                            self._handle_watch_sigint()
                            raise
                        continue

                    prompt = self.current_messenger.nickname if self.current_messenger else self.PROMPT
                    user_input = await self.session.prompt_async(f'({prompt})~# ')
                except KeyboardInterrupt:
                    self.update_cli.display(f"CTRL+C caught, type `exit` to quit Messenger.", 'information',
                                            reprompt=False)
                    continue
                except EOFError:
                    break

                if not user_input.strip():
                    continue

                timestamp = self.logger.now()
                output_path = None
                with self.logger.capture() as output:
                    try:
                        parts = user_input.split()
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
                        self.update_cli.log_unexpected_error(e)

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

    @require_messenger
    async def start_local_forwarder(self, forwarder_config):
        """
        Start a local port forwarder.

        required:
          forwarder_config         Format: listening_host:listening_port:destination_host:destination_port
                                   IPv6 addresses must be wrapped in brackets.

        examples:
          local 127.0.0.1:8080:example.com:9090
          local [::1]:8080:[::1]:80
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
        Start a remote port forwarder.

        required:
          forwarder_config         Format: listening_host:listening_port:destination_host:destination_port
                                   IPv6 addresses must be wrapped in brackets.

        examples:
          remote 0.0.0.0:8080:127.0.0.1:80
          remote [::]:8080:[::1]:80
        """
        messenger = self.current_messenger
        forwarder = RemotePortForwarder(messenger, forwarder_config, self.update_cli)

        # Is there already a forwarder on this listening endpoint?
        existing = next(
            (f for f in messenger.forwarders
             if isinstance(f, RemotePortForwarder)
             and f.listening_host == forwarder.listening_host
             and int(f.listening_port) == int(forwarder.listening_port)),
            None
        )
        if existing is not None:
            if not existing.is_orphan:
                # Already a configured forward here -- don't make a duplicate.
                self.update_cli.display(
                    f'Messenger `{messenger.nickname}` already has a Remote Port Forwarder '
                    f'({forwarder.listening_host}:{forwarder.listening_port}).',
                    'error', reprompt=False, display_module='forwarders'
                )
                return
            # Adopt the orphan: set its destination, send NO bind request (the
            # client is already listening under this bind_id).
            existing.destination_host = forwarder.destination_host
            existing.destination_port = forwarder.destination_port
            self.update_cli.display(
                f'Messenger `{messenger.nickname}` configured a {existing.NAME} {existing._endpoint_str()}.',
                'success', reprompt=False, display_module='forwarders'
            )
            return

        # Fresh forward -- ask the client to bind.
        await forwarder.start()
        messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_socks_proxy(self, forwarder_config):
        """
        Start a SOCKS server.

        required:
          forwarder_config         Format: listening_port or listening_host:listening_port
                                   IPv6 addresses must be wrapped in brackets.

        examples:
          socks 9050
          socks 127.0.0.1:9050
          socks [::1]:9050
        """
        messenger = self.current_messenger
        forwarder = SocksProxy(messenger, forwarder_config, self.update_cli)
        success = await forwarder.start()
        if success:
            messenger.forwarders.append(forwarder)
        return

    @require_messenger
    async def start_scanner(self, ips, ports=None, concurrency=50, top_ports=100, force_concurrency=False):
        """
        Start a scan against IPs and ports.

        required:
          ips                      IPs, CIDRs, or ranges to scan.

        optional:
          ports                    Specific ports/ranges to scan (e.g., 80,443 or 1-1024).
          --concurrency            Max concurrent scan attempts (default: 50).
          --top-ports              Use top N ports if ports not specified (default: 100).
          --force-concurrency      Bypass the 1000 concurrency cap.

        examples:
          portscan 192.168.1.10
          portscan 10.0.0.0/24 --top-ports 1000 --concurrency 100
          portscan 10.0.0.0/16 --concurrency 2000 --force-concurrency
        """
        try:
            concurrency = int(concurrency)
        except (ValueError, TypeError):
            self.update_cli.display(f'{concurrency} is not a valid concurrency.', 'error', reprompt=False)
            return
        if concurrency < 1:
            self.update_cli.display('Concurrency must be at least 1.', 'error', reprompt=False)
            return
        if concurrency > 1000 and not force_concurrency:
            self.update_cli.display('Concurrency cannot exceed 1000. Use --force-concurrency to bypass.', 'error', reprompt=False)
            return
        try:
            top_ports = int(top_ports)
        except (ValueError, TypeError):
            self.update_cli.display(f'{top_ports} is not a valid integer.', 'error', reprompt=False)
            return

        scanner = Scanner(ips, ports, int(top_ports), self.update_cli, self.current_messenger, int(concurrency))
        self.current_messenger.scanners.append(scanner)
        self.current_messenger.supervisor.spawn(scanner.start(), label=f'scanner:{scanner.identifier}')

    def _resolve_messenger(self, id=None):
        if id is None:
            if self.current_messenger is None:
                self.update_cli.display('Please specify a messenger or interact with one first.', 'error', reprompt=False)
                return None
            return self.current_messenger
        for messenger in self.messengers:
            if id in (messenger.identifier, messenger.nickname):
                return messenger
        self.update_cli.display(f'`{id}` not found.', 'error', reprompt=False)
        return None

    async def _stop_forwarder(self, forwarder):
        if isinstance(forwarder, RemotePortForwarder) and not forwarder.forwarding:
            forwarder.close_all_clients()
            self.update_cli.display(
                f'Removed unconfigured remote port forward `{forwarder.nickname}`.',
                'information', reprompt=False, display_module='forwarders'
            )
        else:
            await forwarder.stop()
            self.update_cli.display(
                f'Removed `{forwarder.nickname}` from forwarders.',
                'information', reprompt=False, display_module='forwarders'
            )

    async def stop(self, id, messenger_id=None):
        """
        Stop a forwarder or scanner by ID, or stop all on a messenger.

        required:
          id                       ID of the forwarder/scanner, or "all".

        optional:
          messenger_id             Messenger to stop all on. Defaults to current.

        examples:
          stop NkMCyCrrcP
          stop all
          stop all dc01
        """
        if id == 'all':
            messenger = self._resolve_messenger(messenger_id)
            if not messenger:
                return
            if not messenger.forwarders and not messenger.scanners:
                self.update_cli.display('Nothing to stop.', 'information', reprompt=False)
                return
            self.update_cli.display(
                f'Messenger `{messenger.nickname}` is attempting to stop all forwarders and scanners.',
                'success', reprompt=False, display_module='messengers'
            )
            for f in list(messenger.forwarders):
                messenger.forwarders.remove(f)
                await self._stop_forwarder(f)
            for s in list(messenger.scanners):
                await s.stop()
            return

        for messenger in self.messengers:
            target = None
            for i, f in enumerate(messenger.forwarders):
                if id in (f.identifier, f.nickname):
                    target = messenger.forwarders.pop(i)
                    break
            if target is not None:
                await self._stop_forwarder(target)
                return
            for scanner in messenger.scanners:
                if id not in (scanner.identifier, scanner.nickname):
                    continue
                await scanner.stop()
                return
        self.update_cli.display(f'`{id}` not found', 'error', reprompt=False)

    async def adaptative(self, id=None):
        """
        Turn adaptive polling on and off.

        optional:
          id                       ID or name of the HTTP messenger.
                                   Defaults to the current messenger if interacting.

        examples:
          adaptative
          adaptative dc01
        """
        target = self._resolve_messenger(id)
        if target is None:
            return
        if not isinstance(target, HTTPMessenger):
            self.update_cli.display('Adaptive polling is only available for HTTP messengers.', 'error', reprompt=False)
            return
        if target.checked_out:
            self.update_cli.display(f'Messenger `{target.nickname}` is killed.', 'error', reprompt=False)
            return
        target.adaptative = not target.adaptative
        state = 'on' if target.adaptative else 'off'
        self.update_cli.display(f'Adaptive polling {state} for Messenger `{target.nickname}`.', 'success',
                                reprompt=False, display_module='messengers')

    async def kill(self, id=None):
        """
        Kill a messenger by sending a checkout signal.

        optional:
          id                       ID or name of the messenger to kill.
                                   Defaults to the current messenger if interacting.

        examples:
          kill NkMCyCrrcP
          kill dc01
          kill
        """
        target = self._resolve_messenger(id)
        if not target:
            return
        target.checked_out = True
        await target.send_message_downstream(CheckOutMessage())
        self.update_cli.display(
            f'Queued kill signal for Messenger `{target.nickname}`.',
            'success', reprompt=False, display_module='messengers'
        )

    async def rename(self, id_or_name, name=None):
        """
        Rename a messenger, forwarder, or scanner.

        required:
          id_or_name               ID or current name of the target, or the new
                                   name when interacting with a messenger.

        optional:
          name                     The new name to assign. Required unless
                                   interacting with a messenger.

        examples:
          rename NkMCyCrrcP dc01
          rename dc01 webserver
          rename dc01
        """
        if name is None:
            if self.current_messenger is None:
                self.update_cli.display('Please specify both an ID and a name, or interact with a messenger first.', 'error', reprompt=False)
                return
            name = id_or_name
            id = self.current_messenger.identifier
        else:
            id = id_or_name

        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            self.update_cli.display('Names may only contain letters, numbers, hyphens, and underscores.', 'error', reprompt=False)
            return

        if name in self.commands:
            self.update_cli.display(f'`{name}` is a command and cannot be used as a name.', 'error', reprompt=False)
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
        if isinstance(target, Messenger):
            module = 'messengers'
        elif isinstance(target, Scanner):
            module = 'scanners'
        else:
            module = 'forwarders'
        self.update_cli.display(f'`{old}` is now known as `{name}`.', 'success', reprompt=False, display_module=module)


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
