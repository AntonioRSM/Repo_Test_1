"""Entry point: python -m vault_engine [--port N]. Prints the bound port on the first line."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time

import psutil
import uvicorn


def exit_with_parent() -> None:
    """Stops the engine if the desktop app that started it dies without cleaning up."""
    parent = os.environ.get("WSOS_PARENT_PID")
    if not parent:
        return

    def watch() -> None:
        while psutil.pid_exists(int(parent)):
            time.sleep(2)
        os._exit(0)

    threading.Thread(target=watch, name="parent-watchdog", daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(prog="vault_engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    port = args.port
    if port == 0:
        with socket.socket() as probe:
            probe.bind((args.host, 0))
            port = probe.getsockname()[1]

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    exit_with_parent()
    # The desktop app reads this line to learn where to connect.
    print(f"VAULT_ENGINE_PORT={port}", flush=True)
    uvicorn.run("vault_engine.app:app", host=args.host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
