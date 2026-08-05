import re

_ANSI_ESCAPE = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')


def strip_ansi(text):
    """
    Remove ANSI escape codes from a string.

    Args:
        text (str): Text that may contain ANSI escape codes.

    Returns:
        str: Text without ANSI escape codes.
    """
    return _ANSI_ESCAPE.sub('', text)


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


def bold_text(text):
    """
    Returns bolded text using ANSI escape codes.

    Args:
        text (str): The text to bold.

    Returns:
        str: Bolded text.
    """
    return "\033[1m" + text + "\033[0m"