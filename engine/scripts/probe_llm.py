"""Sends the engine's rerank prompt straight to a local model and prints the raw reply and timing."""

import json
import sys
import time

import httpx

from vault_engine.app import RERANK_PROMPT

base, model = sys.argv[1], sys.argv[2]
extra = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
passages = "\n\n".join(
    f"[{i}] {t}"
    for i, t in enumerate(
        [
            "Le ferie aziendali vanno richieste con almeno 30 giorni di anticipo tramite il portale HR.",
            "La mensa aziendale è aperta dalle 12:00 alle 14:30 al piano terra.",
        ],
        start=1,
    )
)
payload = {
    "model": model,
    "messages": [{"role": "user", "content": RERANK_PROMPT.format(query="quanti giorni di anticipo per le ferie?", passages=passages)}],
    "temperature": 0.1,
    "max_tokens": 400,
    **extra,
}
start = time.time()
resp = httpx.post(f"{base}/v1/chat/completions", json=payload, timeout=600).json()
print(f"{time.time() - start:.1f}s")
choice = resp["choices"][0]
print("finish_reason:", choice.get("finish_reason"))
print("content:", repr(choice["message"].get("content")))
print("reasoning:", repr((choice["message"].get("reasoning_content") or "")[:600]))
print("usage:", json.dumps(resp.get("usage")))
