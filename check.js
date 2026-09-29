// Verifica che il server API di LM Studio sia raggiungibile
module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: "python tts_bridge.py --check"
      }
    }
  ]
}
