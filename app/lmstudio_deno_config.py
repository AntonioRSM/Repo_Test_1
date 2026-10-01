"""Server MCP deno-js per LM Studio: strumento `run_javascript` con accesso al filesystem.

La sandbox JavaScript integrata in LM Studio non permette di aggiungere permessi Deno: questo script
installa Deno (se manca) e aggiunge a ~/.lmstudio/mcp.json un server che esegue gli script con i permessi scelti.

  python lmstudio_deno_config.py                # stampa il blocco da incollare in mcp.json
  python lmstudio_deno_config.py --install      # installa Deno se serve e scrive la voce deno-js
  python lmstudio_deno_config.py --install --allow-read "D:\\Workspace,C:\\pinokio\\api\\Repo_Test_1.git" \\
      --allow-write "D:\\Workspace" --allow-run
"""
import argparse
import io
import json
import os
import platform
import shutil
import sys
import urllib.request
import zipfile

from lmstudio_mcp_config import install, lmstudio_mcp_path

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "deno_js_server.ts")
LOCAL_DENO_DIR = os.path.join(HERE, "bin")
DEFAULT_READ = r"D:\Workspace,C:\pinokio\api\Repo_Test_1.git"
DEFAULT_WRITE = r"D:\Workspace"


def deno_exe_name():
    return "deno.exe" if os.name == "nt" else "deno"


def find_deno():
    candidates = [
        os.path.join(LOCAL_DENO_DIR, deno_exe_name()),
        shutil.which("deno"),
        os.path.join(os.path.expanduser("~"), ".deno", "bin", deno_exe_name()),
    ]
    return next((os.path.abspath(c) for c in candidates if c and os.path.isfile(c)), None)


def deno_target():
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def download_deno():
    url = f"https://github.com/denoland/deno/releases/latest/download/deno-{deno_target()}.zip"
    print(f"Deno non trovato: scarico {url}")
    with urllib.request.urlopen(url) as r:
        data = r.read()
    os.makedirs(LOCAL_DENO_DIR, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extract(deno_exe_name(), LOCAL_DENO_DIR)
    path = os.path.join(LOCAL_DENO_DIR, deno_exe_name())
    os.chmod(path, 0o755)
    return path


def clean_paths(value):
    """Deno non accetta i caratteri jolly: "D:\\Workspace\\*" diventa "D:\\Workspace" (vale per tutte le sottocartelle)."""
    paths = []
    for p in value.split(","):
        p = p.strip().strip('"')
        while p.endswith(("*", "\\", "/")) and len(p) > 3:
            p = p[:-1]
        if p:
            paths.append(p)
    return ",".join(paths)


def script_flags(allow_read, allow_write, allow_run, allow_net, allow_env):
    flags = []
    if allow_read:
        flags.append(f"--allow-read={clean_paths(allow_read)}")
    if allow_write:
        flags.append(f"--allow-write={clean_paths(allow_write)}")
    if allow_run:
        flags.append("--allow-run")
    if allow_net:
        flags.append("--allow-net")
    if allow_env:
        flags.append("--allow-env")
    return flags


def server_entry(deno, flags):
    return {
        "command": deno,
        "args": ["run", "--quiet", "--no-prompt", f"--allow-run={deno}", SERVER, f"--deno={deno}", *flags],
    }


def main():
    p = argparse.ArgumentParser(description="Server MCP deno-js (run_javascript con accesso al filesystem) per LM Studio")
    p.add_argument("--install", action="store_true", help="installa Deno se serve e scrive la voce in ~/.lmstudio/mcp.json")
    p.add_argument("--allow-read", default=DEFAULT_READ, help=f"cartelle leggibili, separate da virgola (default {DEFAULT_READ})")
    p.add_argument("--allow-write", default=DEFAULT_WRITE, help=f"cartelle scrivibili, separate da virgola (default {DEFAULT_WRITE})")
    p.add_argument("--allow-run", action=argparse.BooleanOptionalAction, default=True,
                   help="consente agli script di avviare processi esterni (default sì; --no-allow-run per vietarlo)")
    p.add_argument("--allow-net", action="store_true", help="consente l'accesso alla rete")
    p.add_argument("--allow-env", action="store_true", help="consente la lettura delle variabili d'ambiente")
    p.add_argument("--mcp-json", default="", help="percorso di mcp.json (default ~/.lmstudio/mcp.json)")
    args = p.parse_args()

    deno = find_deno()
    if not deno:
        if not args.install:
            raise SystemExit("Deno non trovato: esegui con --install per scaricarlo in app/bin.")
        deno = download_deno()
    flags = script_flags(args.allow_read, args.allow_write, args.allow_run, args.allow_net, args.allow_env)
    entry = server_entry(deno, flags)
    if args.install:
        path = install(args.mcp_json or lmstudio_mcp_path(), entry, name="deno-js")
        print(f"Server MCP 'deno-js' aggiunto a {path} (copia di sicurezza: {path}.bak se il file esisteva).")
        print("Permessi degli script: " + " ".join(flags))
        print("In LM Studio: Program > Integrations, attiva 'mcp/deno-js' e disattiva la sandbox JavaScript integrata.")
    else:
        print(json.dumps({"mcpServers": {"deno-js": entry}}, indent=2))


if __name__ == "__main__":
    main()
