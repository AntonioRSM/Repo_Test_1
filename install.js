module.exports = {
  requires: {
    bundle: "ai"
  },
  run: [
    // 1. PyTorch per la GPU di questo PC
    {
      method: "script.start",
      params: {
        uri: "torch.js",
        params: { venv: "env", path: "app" }
      }
    },
    // 2. F5-TTS + dipendenze per il collegamento a LM Studio (MCP)
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: [
          "uv pip install f5-tts mcp hf_xet openai gradio_client pydub",
          "uv pip uninstall torchcodec"
        ]
      }
    },
    // 3. Rileva l'hardware e sceglie il modello F5-TTS
    {
      method: "script.start",
      params: { uri: "detect.js" }
    },
    {
      method: "notify",
      params: {
        html: "Installazione completata. Avvia il server di LM Studio (porta 1234) e premi 'Avvia'."
      }
    }
  ]
}
