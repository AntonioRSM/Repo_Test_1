"""Checks whether a local model returns OpenAI-style tool_calls (streaming), and how fast."""

import json
import sys
import time

import httpx

base, model = sys.argv[1], sys.argv[2]
tools = [
    {
        "type": "function",
        "function": {
            "name": "vault_search",
            "description": "Search the user's local document vaults.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look for"}},
                "required": ["query"],
            },
        },
    }
]
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "You are a helpful assistant. Use tools when they help."},
        {"role": "user", "content": "Cerca nei miei documenti la penale per ritardata consegna."},
    ],
    "tools": tools,
    "temperature": 0.2,
    "max_tokens": 300,
    "stream": True,
    "reasoning_effort": "none",
}
start = time.time()
first = None
text, calls, finish = "", {}, None
with httpx.stream("POST", f"{base}/v1/chat/completions", json=payload, timeout=600) as resp:
    for line in resp.iter_lines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        chunk = json.loads(line[6:])
        delta = chunk["choices"][0].get("delta", {})
        finish = chunk["choices"][0].get("finish_reason") or finish
        if first is None and (delta.get("content") or delta.get("tool_calls")):
            first = time.time() - start
        text += delta.get("content") or ""
        for tc in delta.get("tool_calls") or []:
            slot = calls.setdefault(tc["index"], {"name": "", "arguments": ""})
            fn = tc.get("function", {})
            slot["name"] += fn.get("name") or ""
            slot["arguments"] += fn.get("arguments") or ""
print(f"first token {first:.1f}s, total {time.time() - start:.1f}s, finish={finish}")
print("text:", repr(text))
print("tool_calls:", json.dumps(calls, ensure_ascii=False))
