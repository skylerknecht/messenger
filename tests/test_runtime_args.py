#!/usr/bin/env python3
"""Black-box checks for generated-client runtime argument handling."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def command_for(kind, artifact):
    path = Path(artifact)
    if kind == "python":
        return [sys.executable, str(path)]
    if kind == "node":
        return ["node", str(path)]
    if path.suffix.lower() == ".exe":
        return [str(path)]
    return ["dotnet", str(path)]


def run(kind, artifact, extra):
    started = time.monotonic()
    process = subprocess.run(
        command_for(kind, artifact) + extra,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
    )
    return process.returncode, process.stdout, time.monotonic() - started


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--clients", nargs="+", choices=("python", "node", "csharp"),
                        default=("python", "node", "csharp"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures = []
    base = [
        "--server-url", "http://127.0.0.1:1",
        "--encryption-key", "runtime-key",
        "--user-agent", "Runtime Argument Conformance/0.9.2",
        "--retry-duration", "0",
        "--retry-attempts", "0",
    ]

    for kind in args.clients:
        artifact = manifest[kind]
        try:
            _, output, elapsed = run(kind, artifact, ["--definitely-unknown", *base])
            check("definitely-unknown" in output, f"{kind} did not warn about an unknown argument: {output}")
            check("Attempting to reconnect" not in output, f"{kind} ignored zero retry attempts: {output}")
            check(elapsed < 10, f"{kind} zero-retry process took {elapsed:.1f}s")
            print(f"PASS {kind}: unknown argument and zero retry")
        except Exception as error:
            failures.append(f"{kind}: unknown/zero-retry: {error}")

        try:
            # Put the missing-value option last. Python uses argparse's error;
            # Node/C# emit their own warning and continue with embedded config.
            _, output, _ = run(kind, artifact, [*base, "--user-agent"])
            lowered = output.lower()
            check(
                "requires a value" in lowered or "expected one argument" in lowered,
                f"{kind} did not reject a missing value: {output}",
            )
            print(f"PASS {kind}: missing argument value")
        except Exception as error:
            failures.append(f"{kind}: missing value: {error}")

        try:
            _, output, _ = run(kind, artifact, [*base, "--proxy", "http://127.0.0.1:1"])
            check("could not find argument `--proxy`" not in output.lower(), f"{kind} rejected --proxy: {output}")
            if kind == "node":
                check("no native support for proxies" in output.lower(), f"Node did not state proxy limitation: {output}")
            print(f"PASS {kind}: proxy argument behavior")
        except Exception as error:
            failures.append(f"{kind}: proxy: {error}")

    if failures:
        print("\n".join(f"FAIL {failure}" for failure in failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
