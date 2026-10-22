"""Entry point: python -m vault_engine [--port N]. Prints the bound port on the first line."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import threading
import time

import psutil
import uvicorn

LOCALHOST = ("127.0.0.1", "::1", "localhost")


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


async def _serve(args: argparse.Namespace) -> None:
    config = uvicorn.Config("vault_engine.app:app", host=args.host, port=args.port, log_level=args.log_level)
    server = uvicorn.Server(config)

    async def announce_port() -> None:
        # Wait until uvicorn has bound its socket(s), then publish the real port.
        # Binding happens exactly once inside uvicorn.run: no probe socket, no TOCTOU race.
        while not server.started:
            await asyncio.sleep(0.05)
        for http_server in server.servers:
            for sock in http_server.sockets:
                print(f"VAULT_ENGINE_PORT={sock.getsockname()[1]}", flush=True)
                return

    await asyncio.gather(server.serve(), announce_port())


def main() -> None:
    parser = argparse.ArgumentParser(prog="vault_engine")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="interfaccia di ascolto: solo 127.0.0.1 (consigliato, default) o localhost; "
        "valori di rete espongono l'API a ogni host raggiungibile",
    )
    parser.add_argument("--port", type=int, default=0, help="0 = porta libera scelta dal sistema")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    if args.host not in LOCALHOST:
        logging.getLogger(__name__).warning(
            "--host %s espone l'API fuori dal loopback: assicurati che WSOS_TOKEN sia impostato", args.host
        )

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    exit_with_parent()
    asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
