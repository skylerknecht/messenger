import readline
import sys


class Output:
    def __init__(self):
        self.prompt = '(messenger)~# '

    def display(self, stdout):
        print('\r', end='')
        print(stdout)
        print(self.prompt + readline.get_line_buffer(), end='')
        sys.stdout.flush()


output = Output()
display = output.display
