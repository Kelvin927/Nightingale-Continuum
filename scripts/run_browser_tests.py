#!/usr/bin/env python3
"""Run Playwright against checkout-owned API and web server ports."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def reserve_two_ports() -> tuple[int, int]:
    """Ask the OS for two distinct loopback ports while both are reserved."""
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as api_socket,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as web_socket,
    ):
        api_socket.bind(("127.0.0.1", 0))
        web_socket.bind(("127.0.0.1", 0))
        return api_socket.getsockname()[1], web_socket.getsockname()[1]


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("npm was not found on PATH", file=sys.stderr)
        return 2
    api_port, web_port = reserve_two_ports()
    environment = os.environ.copy()
    environment["NIGHTINGALE_E2E_API_PORT"] = str(api_port)
    environment["NIGHTINGALE_E2E_WEB_PORT"] = str(web_port)
    print(f"Playwright isolated ports: API {api_port}, web {web_port}")
    return subprocess.run(  # noqa: S603
        [npm, "--prefix", "frontend", "run", "test:e2e"],
        cwd=ROOT,
        env=environment,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
