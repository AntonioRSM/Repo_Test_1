"""Stampa il blocco da incollare in LM Studio (Program > Install > Edit mcp.json)."""
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
print(json.dumps({"mcpServers": {"f5-tts": {
    "command": sys.executable,
    "args": [os.path.join(here, "mcp_server.py")],
}}}, indent=2))
