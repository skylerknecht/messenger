import os
import re
import sys

base_directory = os.path.dirname(__file__)

try:
    from setuptools import setup, find_packages
except ImportError:
    print('This project needs setuptools in order to build. Install it using your package')
    print('manager (usually python-setuptools) or via pip (pip install setuptools).')
    sys.exit(1)

try:
    with open(os.path.join(base_directory, 'README.md')) as file_h:
        long_description = file_h.read()
except OSError:
    sys.stderr.write('README.md is unavailable, cannot generate the long description\n')
    long_description = None

with open(os.path.join(base_directory, 'messenger', '__init__.py')) as file_h:
    match = re.search(r'^__version__\s*=\s*([\'"])(?P<version>\d+(\.\d)*)\1$', file_h.read(), flags=re.MULTILINE)
if match is None:
    raise RuntimeError('Unable to find the version information')
version = match.group('version')

DESCRIPTION = """\
Messenger uses a client-server architecture to establish a SOCKS5 tunnel. Once the client connects, the \
server will create a local SOCKS5 tunnel that can be used to interact with the local network the client is connected to.\
"""

setup(
    name='messenger',
    version=version,
    packages=find_packages(),
    install_requires=[
        'aiohttp',
        'aioconsole'
    ],
    author='Skyler Knecht',
    author_email='skyler.knecht@outlook.com',
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/skylerknecht/messenger',
    license='BSD-3-Clause',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
    scripts=['messenger-server', 'messenger-client']
)
