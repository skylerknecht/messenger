import random
import string
import hashlib

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


def generate_encryption_key(min_len=10, max_len=20):
    length = random.randint(min_len, max_len)  # Random length between min_length and max_length
    letters = string.ascii_letters   # Contains both uppercase and lowercase letters
    return ''.join(random.choice(letters) for _ in range(length))


def generate_hash(hash_input: str) -> bytes:
    hasher = hashlib.sha256()
    hash_input = hash_input.encode('utf-8')
    hasher.update(hash_input)
    return hasher.digest()