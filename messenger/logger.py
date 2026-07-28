import os
import re
import sys
from datetime import datetime


class Logger:
    ANSI_ESCAPE = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')

    def __init__(self):
        self.terminal = sys.stdout
        log_dir = os.path.join(os.path.expanduser('~'), '.messenger', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f'{datetime.now().strftime("%Y-%m-%d")}.log')
        self.log_file = open(path, 'a')
        sys.stdout = self

    def write(self, text):
        self.terminal.write(text)
        clean = self.ANSI_ESCAPE.sub('', text)
        self.log_file.write(clean)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()

    def close(self):
        sys.stdout = self.terminal
        self.log_file.close()
