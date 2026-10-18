"""Drives one agent conversation over the HTTP API, approving every tool call, and prints a timeline.

Usage: python scripts/agent_e2e.py <engine base url> "<prompt>" [deny_tool]
"""

import json
import sys
import time

import httpx

base, prompt = sys.argv[1], sys.argv[2]
deny = sys.argv[3] if len(sys.argv) > 3 else None
client = httpx.Client(base_url=base, timeout=30)
start = time.time()
thread = client.post("/agent/threads", json={}).json()
client.post(f"/agent/threads/{thread['id']}/messages", json={"content": prompt}).raise_for_status()
handled = set()
while True:
    status = client.get(f"/agent/threads/{thread['id']}").json()["status"]
    for call in status["pending"]:
        if call["id"] in handled:
            continue
        handled.add(call["id"])
        decision = "deny" if call["name"] == deny else "allow"
        print(f"{time.time() - start:6.0f}s  {decision.upper():5} {call['name']} {call['arguments'][:140]}", flush=True)
        client.post(f"/agent/threads/{thread['id']}/approvals/{call['id']}", json={"decision": decision})
    if not status["running"]:
        break
    time.sleep(2)
print(f"{time.time() - start:6.0f}s  finished")
for message in client.get(f"/agent/threads/{thread['id']}").json()["messages"]:
    meta = message["meta"]
    if message["role"] == "assistant":
        usage = meta.get("usage") or {}
        print(f"--- assistant step {meta.get('step')} prompt={usage.get('prompt_tokens')} out={usage.get('completion_tokens')} error={meta.get('error')}")
        if message["content"]:
            print(message["content"])
    elif message["role"] == "tool":
        print(f"--- tool {message['name']} ok={meta.get('ok')} {meta.get('seconds')}s {json.dumps(meta.get('error'))}")
