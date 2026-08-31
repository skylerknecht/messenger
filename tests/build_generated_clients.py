#!/usr/bin/env python3
"""Generate the exact pinned clients and compile the C# artifact for CI."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KEY = "embedded-key-overridden-by-e2e"


def run(command):
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True)


def retarget_net8(csharp_project):
    project_file = csharp_project / "MessengerClient.csproj"
    project = project_file.read_text(encoding="utf-8")
    project = project.replace("<TargetFramework>net472</TargetFramework>", "<TargetFramework>net8.0</TargetFramework>")
    project = re.sub(
        r"\s*<ItemGroup>\s*<PackageReference Include=\"Microsoft\.NETFramework\.ReferenceAssemblies\".*?</ItemGroup>",
        "",
        project,
        flags=re.DOTALL,
    )
    project = re.sub(
        r"\s*<ItemGroup>\s*<Reference Include=\"System\.Net\.Http\"\s*/>\s*</ItemGroup>",
        "",
        project,
        flags=re.DOTALL,
    )
    project_file.write_text(project, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-framework", choices=("net472", "net8.0"), default="net8.0")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    python_client = output / "messenger-client.py"
    node_client = output / "messenger-client.js"
    csharp_project = output / "MessengerClient"
    common = [
        "--server-url", "unused.invalid:1",
        "--encryption-key", KEY,
        "--user-agent", "Embedded Builder UA/0.9.2",
        "--retry-duration", "12",
        "--retry-attempts", "4",
    ]
    run([sys.executable, ROOT / "messenger-builder", "python", "--name", python_client, "--no-obfuscate", *common])
    run([sys.executable, ROOT / "messenger-builder", "nodejs", "--name", node_client, *common])
    run([sys.executable, ROOT / "messenger-builder", "csharp", "--name", csharp_project, *common])

    if args.target_framework == "net8.0":
        retarget_net8(csharp_project)

    run(["dotnet", "build", csharp_project / "MessengerClient.csproj", "-c", "Release", "--nologo"])

    if args.target_framework == "net472":
        csharp_client = csharp_project / "bin" / "Release" / "net472" / "MessengerClient.exe"
    else:
        csharp_client = csharp_project / "bin" / "Release" / "net8.0" / "MessengerClient.dll"
    if not csharp_client.is_file():
        raise SystemExit(f"compiled C# client was not produced: {csharp_client}")

    manifest = {
        "python": str(python_client),
        "node": str(node_client),
        "csharp": str(csharp_client),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

