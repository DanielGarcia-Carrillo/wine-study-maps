"""The fail-fast local and CI gate; run after installing the locked dev dependency group."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    commands = [
        ["-m", "ruff", "check", "scripts", "tests", "typings"],
        ["-m", "ruff", "format", "--check", "scripts", "tests", "typings"],
        ["-m", "mypy"],
        ["scripts/check_project.py"],
        ["scripts/source_geodata.py"],
        ["-m", "unittest", "discover", "-s", "tests"],
        ["scripts/validate_render.py"],
    ]
    started = time.monotonic()
    for command in commands:
        print("+ python " + " ".join(command), flush=True)
        result = subprocess.run([sys.executable, *command], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    print(f"PASS: quality gate ({time.monotonic() - started:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
