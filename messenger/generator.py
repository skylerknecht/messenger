import secrets
import string
import hashlib

alphanumeric = string.ascii_letters + string.digits
alphabet = string.ascii_letters


def digit_identifier(length: int = 10) -> str:
    """
    Generate random digits (1-9) for a length of *length*.

    :param: int length: The amount of random digits to concatenate.
    :return: The generated digit identifier.
    :rtype: str
    """
    return ''.join(str(secrets.randbelow(9) + 1) for _ in range(length))


def string_identifier(length: int = 10) -> str:
    """
    Generate random alphabetic characters for a length of *length*.

    :param: int length: The amount of random characters to concatenate.
    :return: The generated string identifier.
    :rtype: str
    """
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def alphanumeric_identifier(length: int = 10) -> str:
    """
    Generate random alphanumeric characters for a length of *length*.

    :param: int length: The amount of random characters to concatenate.
    :return: The generated string identifier.
    :rtype: str
    """
    return ''.join(secrets.choice(alphanumeric) for _ in range(length))


def generate_encryption_key(min_len=10, max_len=20):
    length = secrets.randbelow(max_len - min_len + 1) + min_len
    letters = string.ascii_letters
    return ''.join(secrets.choice(letters) for _ in range(length))


def generate_hash(hash_input: str) -> bytes:
    hasher = hashlib.sha256()
    hash_input = hash_input.encode('utf-8')
    hasher.update(hash_input)
    return hasher.digest()