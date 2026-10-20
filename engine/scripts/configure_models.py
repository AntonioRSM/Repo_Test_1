"""Sets the default embedding model and LLM after installation, without overriding choices
the user already made in Settings.

Usage (from engine/):  .venv\\Scripts\\python.exe scripts\\configure_models.py --provider ollama \\
                           --embedding bge-m3:latest --llm qwen3:4b
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vault_engine.config import ModelRef, SettingsStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["lmstudio", "ollama"], required=True)
    parser.add_argument("--embedding")
    parser.add_argument("--llm")
    args = parser.parse_args()

    store = SettingsStore()
    current = store.get()
    patch = {}
    for field, model in (("default_embedding", args.embedding), ("llm", args.llm)):
        if not model:
            continue
        if getattr(current, field) is not None:
            print(f"{field}: già impostato ({getattr(current, field).model}), non lo cambio")
            continue
        patch[field] = ModelRef(provider=args.provider, model=model).model_dump()
        print(f"{field}: {args.provider} / {model}")
    if patch:
        store.update(patch)
    print(f"Impostazioni: {store.path}")


if __name__ == "__main__":
    main()
