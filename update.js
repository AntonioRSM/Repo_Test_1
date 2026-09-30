module.exports = {
  run: [
    { method: "shell.run", params: { message: "git pull" } },
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        // --upgrade-package: aggiorna solo questi, senza trascinare torch/torchaudio a versioni
        // che richiedono torchcodec (su Windows non disponibile)
        message: [
          "uv pip install f5-tts mcp openai gradio_client pydub soundfile imageio-ffmpeg --upgrade-package f5-tts --upgrade-package mcp",
          "uv pip uninstall torchcodec"
        ]
      }
    }
  ]
}
