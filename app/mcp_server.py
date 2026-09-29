"""Server MCP per LM Studio: aggiunge alla chat di LM Studio lo strumento
`text_to_speech`, così l'LLM può generare file audio con F5-TTS.
Configurazione: vedi `python lmstudio_mcp_config.py`.
"""
import contextlib
import sys

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from tts_bridge import Speaker, load_config

# Il protocollo MCP viaggia su stdout: i log di F5-TTS vanno su stderr.
with contextlib.redirect_stdout(sys.stderr):
    speaker = Speaker(load_config())
mcp = MCPServer("f5-tts")


@mcp.tool()
def text_to_speech(text: str, speed: float = 1.0) -> str:
    """Converte il testo in parlato con F5-TTS e restituisce il percorso del file .wav creato."""
    with contextlib.redirect_stdout(sys.stderr):
        path = speaker.speak(text, speed=speed)
    return f"Audio salvato in: {path}"


if __name__ == "__main__":
    mcp.run()
