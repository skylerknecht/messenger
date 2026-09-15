#!/usr/bin/env python3
"""Detect platform and check build dependencies."""

import platform
import shutil
import subprocess
import sys


def _version(cmd, flag="--version"):
    try:
        out = subprocess.check_output(
            [cmd, flag], stderr=subprocess.STDOUT, text=True, timeout=10
        )
        return out.strip().split("\n")[0]
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def check_node():
    return _version("node")


def check_npm():
    return _version("npm")


def check_dotnet():
    return _version("dotnet")


INSTALL = {
    "node": {
        "Darwin":  "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && nvm install node",
        "Linux":   "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && nvm install node",
        "Windows": "winget install OpenJS.NodeJS.LTS",
    },
    "dotnet": {
        "Darwin":  "curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0",
        "Linux":   "curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0",
        "Windows": "winget install Microsoft.DotNet.SDK.8",
    },
}


def install_cmd(tool):
    return INSTALL.get(tool, {}).get(platform.system(), f"See docs for {tool}")


def check_all():
    system = platform.system()
    machine = platform.machine()
    print(f"[*] Platform: {system} {machine}")

    print(f"[+] Python {sys.version.split()[0]}")

    node_ver = check_node()
    if node_ver:
        print(f"[+] Node.js {node_ver}")
    else:
        print(f"[!] Node.js not found, run the following to install:")
        print(f"    {install_cmd('node')}")

    npm_ver = check_npm()
    if npm_ver:
        print(f"[+] npm {npm_ver}")
    elif node_ver:
        print("[!] npm not found (should be installed with Node.js)")

    dotnet_ver = check_dotnet()
    if dotnet_ver:
        print(f"[+] .NET {dotnet_ver}")
    else:
        print(f"[!] .NET SDK not found, run the following to install:")
        print(f"    {install_cmd('dotnet')}")


if __name__ == "__main__":
    check_all()
