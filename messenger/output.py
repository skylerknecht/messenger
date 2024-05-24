import readline
import sys
from collections import namedtuple

current_status_level = 0
PROMPT = '(messenger)~# '
Status = namedtuple('Status', ['icon', 'color'])

# Define various status levels with corresponding icons and color codes
STATUS_LEVELS = {
    'debug': Status('[DBG]', 'white'),
    'information': Status('[*]', 'cyan'),
    'warning': Status('[!]', 'yellow'),
    'error': Status('[-]', 'red'),
    'success': Status('[+]', 'green')
}

def color_text(text, color):
    # ANSI color codes
    colors = {
        'white': '\033[97m',
        'cyan': '\033[96m',
        'yellow': '\033[93m',
        'red': '\033[91m',
        'green': '\033[92m',
        'reset': '\033[0m'
    }
    return colors.get(color, colors['reset']) + text + colors['reset']


def display(stdout, status='information', status_level=0):
    if not current_status_level >= status_level:
        return
    status_info = STATUS_LEVELS.get(status, STATUS_LEVELS['information'])
    if status == 'debug':
        icon = color_text(f'{status_info.icon}-{status_level}', status_info.color)
    else:
        icon = color_text(status_info.icon, status_info.color)
    print(f'\r{icon} {stdout}')
    print(PROMPT + readline.get_line_buffer(), end='')
    sys.stdout.flush()