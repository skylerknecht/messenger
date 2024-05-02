import atexit
import os
import readline

from messenger.commands import commands


class MessengerCLI:
    MESSENGER_DIR = f'{os.path.expanduser("~")}/.messenger'
    HISTORY_FILE = f'{MESSENGER_DIR}/history'
    PROMPT = '(messenger)~# '

    def __init__(self, messenger_server):
        self.messenger_server = messenger_server
        if not os.path.exists(self.MESSENGER_DIR):
            print(f'Creating {self.MESSENGER_DIR}')
            os.makedirs(self.MESSENGER_DIR)
        if not os.path.exists(self.HISTORY_FILE):
            print(f'Creating {self.HISTORY_FILE}')
            with open(self.HISTORY_FILE, 'w') as f:
                f.write('welcome to messenger')
        try:
            readline.read_history_file(self.HISTORY_FILE)
        except Exception as e:
            print(f'Failed to read history file: {e}')
        readline.parse_and_bind('tab: complete')
        self.completer = Completer(commands.keys())
        readline.set_completer(self.completer.complete_option)
        readline.set_completer_delims(" \t\n\"\\'`@$><=;|&{(")
        atexit.register(readline.write_history_file, self.HISTORY_FILE)

    def run(self):
        print('Welcome to the Messenger CLI, type help or ? to get started.')
        while True:
            try:
                user_input = input(self.PROMPT)
                if not user_input.replace(" ", ""):
                    continue
                if user_input.startswith("exit"):
                    import sys
                    sys.exit(0)
                #self.commands_manager.execute_command(user_input, self.set_cli_properties, self.get_cli_properties)
            except KeyboardInterrupt:
                # ToDo: do we need additional exceptions?
                # ToDo: is there a better way to handle this exception?
                print()  # This puts (connect)~#, the next prompt, on the next line.
class Completer:
    def __init__(self, options):
        self.options = options

    def update_options(self, options):
        self.options.extend(options)

    def complete_option(self, incomplete_option, state):
        """
        Analyzes the length of current line buffer / incomplete_option and
        determines the user(s) completion.

        If the current line buffer is greater or equal to one and the current line
        buffer ends with a trailing space then that indicates the user is attempting
        to complete a multi-worded option. The length of the current line buffer,
        when delimited by a space, must be incremented by one to correctly search
        for the next option.

        Otherwise, generate a list of all current menu options and file names that
        start with the current incomplete_option aka the last line in the buffer.

        Parameters:
                incomplete_option (str()): The current incomplete option.
                state (int()): An integer so that when the function is called
                            recursively by readline it can gather all items
                            within the current finished_option list.

        Returns:
                finished_option (str): Whatever option the callee has not
                                    gathered yet.
        """
        current_line = readline.get_line_buffer()
        current_line_list = current_line.split()
        if len(current_line_list) >= 1 and current_line.endswith(' '):
            current_line_list.append('')
        finished_options = [option for option in self.options if option.startswith(incomplete_option)]
        return finished_options[state]