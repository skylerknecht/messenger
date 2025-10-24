from Crypto import Random
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

def decrypt(key: bytes, ciphertext: bytes) -> bytes:
    # Note that the first AES.block_size bytes of the ciphertext
    # contain the IV
    iv = ciphertext[:16]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    msg = unpad(cipher.decrypt(ciphertext[16:]), AES.block_size)
    return msg

def encrypt(key: bytes, plaintext: bytes) -> bytes:
    # Encrypt the plaintext bytes with a provided key.
    # Generate a new 16 byte IV and include that
    # at the begining of the ciphertext
    iv = Random.new().read(AES.block_size)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    msg = cipher.encrypt(pad(plaintext, AES.block_size))
    return iv + msg
