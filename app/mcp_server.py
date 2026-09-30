"""Server MCP per LM Studio: aggiunge alla chat di LM Studio gli strumenti
- `text_to_speech`: l'LLM genera un file audio con F5-TTS;
- `genera_audiolibro` / `stato_audiolibro`: avviano e seguono la pipeline
  audiobook/audiobook_pipeline.py (capitoli .txt/.md -> MP3).
Configurazione: vedi `python lmstudio_mcp_config.py`.
"""
import contextlib
import sys

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from audiobook_job import AudiobookJob
from tts_bridge import Speaker, load_config

# Il protocollo MCP viaggia su stdout: i log di F5-TTS vanno su stderr.
with contextlib.redirect_stdout(sys.stderr):
    speaker = Speaker(load_config())
mcp = MCPServer("f5-tts")
audiobook = AudiobookJob()


@mcp.tool()
def text_to_speech(text: str, speed: float = 1.0) -> str:
    """Converte il testo in parlato con F5-TTS e restituisce il percorso del file .wav creato."""
    with contextlib.redirect_stdout(sys.stderr):
        path = speaker.speak(text, speed=speed)
    return f"Audio salvato in: {path}"


@mcp.tool()
def genera_audiolibro(file: str = "", formato: str = "mp3", forza: bool = False, solo_testo: bool = False) -> str:
    """Avvia in background la generazione di audiolibri dai capitoli .txt o .md.

    Il testo viene normalizzato con LM Studio (numeri, numeri romani, date, accenti),
    letto con F5-TTS su Pinokio e salvato come MP3 nelle cartelle di audiobook/config.json.
    file: nome di un solo capitolo (es. "capitolo_01.txt"); vuoto = tutti i .txt e .md della cartella di input.
    formato: "mp3" oppure "wav". forza: rigenera anche i capitoli già esportati.
    solo_testo: solo normalizzazione, senza audio (per controllare il testo).
    La generazione dura minuti o ore: dopo l'avvio usa stato_audiolibro per l'avanzamento.
    """
    try:
        return audiobook.start(file, formato, forza, solo_testo)
    except (FileNotFoundError, ValueError) as e:
        return f"Impossibile avviare: {e}"


@mcp.tool()
def stato_audiolibro(righe: int = 25) -> str:
    """Mostra lo stato della generazione avviata con genera_audiolibro e le ultime righe del log."""
    return audiobook.status(max(1, min(righe, 200)))


if __name__ == "__main__":
    mcp.run()
