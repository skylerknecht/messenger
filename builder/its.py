"""Platform predicates.

Usage:
    from builder import its
    if its.windows: ...
    if its.linux:   ...
"""

import platform

_system = platform.system()

windows = _system == "Windows"
linux = _system == "Linux"
darwin = _system == "Darwin"
macos = darwin
