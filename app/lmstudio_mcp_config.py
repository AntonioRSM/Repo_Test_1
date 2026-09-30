"""Configurazione del server MCP f5-tts per LM Studio.

  python lmstudio_mcp_config.py                 # stampa il blocco da incollare in mcp.json
  python lmstudio_mcp_config.py --install       # lo aggiunge direttamente a ~/.lmstudio/mcp.json
  python lmstudio_mcp_config.py --install --audiobook-dir D:\\Workspace\\epub_build\\audiobook
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def server_entry(audiobook_dir=""):
    entry = {"command": sys.executable, "args": [os.path.join(HERE, "mcp_server.py")]}
    if audiobook_dir:
        entry["env"] = {"AUDIOBOOK_DIR": os.path.abspath(audiobook_dir)}
    return entry


def lmstudio_mcp_path():
    home = os.environ.get("LMSTUDIO_HOME") or os.path.join(os.path.expanduser("~"), ".lmstudio")
    return os.path.join(home, "mcp.json")


def install(path, entry):
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path} non è JSON valido ({e}): correggilo o incolla il blocco a mano.")
        shutil.copyfile(path, path + ".bak")
    elif not os.path.isdir(os.path.dirname(path)):
        raise SystemExit(f"Cartella di LM Studio non trovata: {os.path.dirname(path)} "
                         "(avvia LM Studio almeno una volta o imposta LMSTUDIO_HOME).")
    data.setdefault("mcpServers", {})["f5-tts"] = entry
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def main():
    p = argparse.ArgumentParser(description="Server MCP f5-tts per LM Studio")
    p.add_argument("--install", action="store_true", help="scrive la voce f5-tts in ~/.lmstudio/mcp.json")
    p.add_argument("--audiobook-dir", default="", help="cartella di audiobook_pipeline.py se non è quella del repo")
    p.add_argument("--mcp-json", default="", help="percorso di mcp.json (default ~/.lmstudio/mcp.json)")
    args = p.parse_args()
    entry = server_entry(args.audiobook_dir)
    if args.install:
        path = install(args.mcp_json or lmstudio_mcp_path(), entry)
        print(f"Server MCP 'f5-tts' aggiunto a {path} (copia di sicurezza: {path}.bak se il file esisteva).")
        print("In LM Studio: scheda Program > Integrations, attiva 'mcp/f5-tts' (o riavvia LM Studio).")
    else:
        print(json.dumps({"mcpServers": {"f5-tts": entry}}, indent=2))


if __name__ == "__main__":
    main()
