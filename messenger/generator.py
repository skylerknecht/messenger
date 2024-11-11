import random
import string

# Populate alphabet with uppercase, lowercase characters, and digits
alphanumeric = list(string.ascii_letters + string.digits)  # 'a-z', 'A-Z', and '0-9'
alphabet = list(string.ascii_letters)

def digit_identifier(length: int = 10) -> str:
    """
    Generate random integers from 1 to 9 and concatenate the digits
    together for a length of zero to *length*.

    :param: int length: The amount of random digits to concatenate.
    :return: The generated digit identifier.
    :rtype: str
    """
    _identifier = [str(random.randint(1, 9)) for _ in range(0, length)]
    _identifier = ''.join(_identifier)
    return _identifier

def string_identifier(length: int = 10) -> str:
    """
    Generate random alphanumeric characters and concatenate
    them for a length of zero to *length*.
    :param: int length: The amount of random characters to concatenate.
    :return: The generated string identifier.
    :rtype: str
    """
    _identifier = [alphabet[random.randint(0, len(alphabet) - 1)] for _ in range(0, length)]
    _identifier = ''.join(_identifier)
    return _identifier


def alphanumeric_identifier(length: int = 10) -> str:
    """
    Generate random alphanumeric characters and concatenate
    them for a length of zero to *length*.
    :param: int length: The amount of random characters to concatenate.
    :return: The generated string identifier.
    :rtype: str
    """
    _identifier = [alphanumeric[random.randint(0, len(alphabet) - 1)] for _ in range(0, length)]
    _identifier = ''.join(_identifier)
    return _identifier
