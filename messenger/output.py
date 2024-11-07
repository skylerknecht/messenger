from collections import namedtuple

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


def display(stdout, status='information'):
    status_info = STATUS_LEVELS.get(status, STATUS_LEVELS['information'])
    icon = color_text(status_info.icon, status_info.color)
    print(f'\r{icon} {stdout}')