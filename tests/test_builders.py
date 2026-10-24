#!/usr/bin/env python3
"""Exercise the aggregate and direct builders with every declared option."""

import argparse
import ast
import contextlib
import filecmp
import importlib.util
import io
import itertools
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("python", "nodejs", "csharp")
COMMON_VALUES = {
    "server_url": "http+ws://builder.example.invalid:18443/path",
    "encryption_key": "builder-key-0123456789",
    "user_agent": "Messenger Builder Conformance/0.9.2",
    "proxy": "http://builder-user:builder-pass@proxy.example.invalid:3128",
    "retry_duration": 17.5,
    "retry_attempts": 9,
}


def run(command):
    return subprocess.run(
        [str(part) for part in command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    ).stdout


def common_args(output):
    return [
        "--name", output,
        "--server-url", COMMON_VALUES["server_url"],
        "--encryption-key", COMMON_VALUES["encryption_key"],
        "--user-agent", COMMON_VALUES["user_agent"],
        "--proxy", COMMON_VALUES["proxy"],
        "--retry-duration", str(COMMON_VALUES["retry_duration"]),
        "--retry-attempts", str(COMMON_VALUES["retry_attempts"]),
    ]


class BuilderTests(unittest.TestCase):
    maxDiff = None

    def test_top_level_discovers_all_pinned_builders(self):
        output = run([sys.executable, ROOT / "messenger-builder", "--help"])
        for language in LANGUAGES:
            self.assertIn(language, output)

    def test_aggregate_and_direct_builders_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for language in LANGUAGES:
                with self.subTest(language=language):
                    suffix = {"python": ".py", "nodejs": ".js", "csharp": ""}[language]
                    aggregate = base / f"aggregate-{language}{suffix}"
                    direct = base / f"direct-{language}{suffix}"
                    extra = []
                    if language == "python":
                        extra = ["--non-main-thread"]
                    elif language == "nodejs":
                        extra = ["--electron"]

                    aggregate_output = run(
                        [sys.executable, ROOT / "messenger-builder", language]
                        + common_args(str(aggregate)) + extra
                    )
                    direct_output = run(
                        [sys.executable, ROOT / "builder" / "clients" / language / "builder.py"]
                        + common_args(str(direct)) + extra
                    )
                    self.assertTrue(aggregate.exists(), aggregate_output)
                    self.assertTrue(direct.exists(), direct_output)

                    if language == "csharp":
                        aggregate_files = sorted(
                            path.relative_to(aggregate) for path in aggregate.rglob("*") if path.is_file()
                        )
                        direct_files = sorted(
                            path.relative_to(direct) for path in direct.rglob("*") if path.is_file()
                        )
                        self.assertEqual(aggregate_files, direct_files)
                        for relative in aggregate_files:
                            self.assertEqual(
                                (aggregate / relative).read_bytes(),
                                (direct / relative).read_bytes(),
                                relative,
                            )
                        rendered = (aggregate / "Program.cs").read_text(encoding="utf-8")
                    else:
                        self.assertEqual(aggregate.read_bytes(), direct.read_bytes())
                        rendered = aggregate.read_text(encoding="utf-8")

                    for value in COMMON_VALUES.values():
                        self.assertIn(str(value), rendered)

                    if language == "python":
                        self.assertIn("def run_coro_in_thread", rendered)
                    elif language == "nodejs":
                        self.assertTrue((aggregate.parent / "main.js").is_file())
                        self.assertTrue((aggregate.parent / "renderer.html").is_file())

    def test_each_builder_declares_the_expected_options(self):
        expected_common = {
            "name", "server_url", "encryption_key", "user_agent", "proxy",
            "retry_duration", "retry_attempts",
            "no_adaptive_polling", "no_arg_parsing", "no_print", "exit_on_close",
        }
        expected_extra = {
            "python": {"non_main_thread"},
            "nodejs": {"electron"},
            "csharp": set(),
        }
        for language in LANGUAGES:
            with self.subTest(language=language):
                builder_path = ROOT / "builder" / "clients" / language / "builder.py"
                spec = importlib.util.spec_from_file_location(f"test_builder_{language}", builder_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                parser = argparse.ArgumentParser()
                module.add_arguments(parser)
                destinations = {action.dest for action in parser._actions if action.dest != "help"}
                self.assertEqual(expected_common | expected_extra[language], destinations)
                defaults = parser.parse_args([])
                self.assertEqual(defaults.server_url, "localhost:8080")
                self.assertEqual(defaults.encryption_key, "")
                self.assertEqual(defaults.proxy, "")
                self.assertEqual(defaults.retry_duration, 60.0)
                self.assertEqual(defaults.retry_attempts, 5)

                help_output = run([
                    sys.executable,
                    ROOT / "messenger-builder",
                    language,
                    "--help",
                ])
                for option in expected_common | expected_extra[language]:
                    self.assertIn("--" + option.replace("_", "-"), help_output)

    def test_generated_output_variants(self):
        """Quiet templates must remain valid with every other build-time flag."""
        common_flags = ["--no-print", "--no-arg-parsing", "--no-adaptive-polling", "--exit-on-close"]
        extra_flags = {"python": ["--non-main-thread"], "nodejs": ["--electron"], "csharp": []}
        with tempfile.TemporaryDirectory() as temporary:
            for language in LANGUAGES:
                path = ROOT / "builder" / "clients" / language / "builder.py"
                spec = importlib.util.spec_from_file_location(f"variant_builder_{language}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                parser = argparse.ArgumentParser()
                module.add_arguments(parser)
                flags = common_flags + extra_flags[language]
                for index, enabled in enumerate(itertools.product((False, True), repeat=len(flags))):
                    selected = [flag for flag, active in zip(flags, enabled) if active]
                    with self.subTest(language=language, flags=selected):
                        suffix = {"python": ".py", "nodejs": ".js", "csharp": ""}[language]
                        output = Path(temporary) / language / str(index) / ("client" + suffix)
                        args = parser.parse_args(common_args(str(output)) + selected)
                        with contextlib.redirect_stdout(io.StringIO()):
                            module.build(args)

                        if language == "python":
                            tree = ast.parse(output.read_text(encoding="utf-8"))
                            prints = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                                      and isinstance(node.func, ast.Name) and node.func.id == "print"]
                            self.assertEqual(bool(prints), not args.no_print)
                        elif language == "nodejs":
                            rendered = output.read_text(encoding="utf-8")
                            self.assertEqual(bool(re.search(r"\bconsole\s*\.", rendered)), not args.no_print)
                            if shutil.which("node") is None:
                                self.skipTest("Node.js is required for generated JavaScript syntax checks")
                            run(["node", "--check", output])
                            if args.electron:
                                run(["node", "--check", output.parent / "main.js"])
                        else:
                            rendered = "\n".join(p.read_text(encoding="utf-8") for p in output.rglob("*.cs"))
                            self.assertEqual(bool(re.search(r"\bConsole\s*\.\s*(?:Write|Out|Error)", rendered)),
                                             not args.no_print)


if __name__ == "__main__":
    unittest.main(verbosity=2)
