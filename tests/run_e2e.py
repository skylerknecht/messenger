#!/usr/bin/env python3
"""Run the shared E2E harness from a generated-client manifest."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    harness = Path(__file__).with_name("e2e_cli.py")
    command = [
        sys.executable,
        str(harness),
        "--python-client", manifest["python"],
        "--node-client", manifest["node"],
        "--csharp-dll", manifest["csharp"],
        "--output-dir", str(args.output_dir),
    ]
    raise SystemExit(subprocess.run(command).returncode)


if __name__ == "__main__":
    main()

