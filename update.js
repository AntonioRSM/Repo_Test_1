module.exports = {
  run: [
    { method: "shell.run", params: { message: "git pull" } },
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: ["uv pip install -U f5-tts mcp openai gradio_client pydub", "uv pip uninstall torchcodec"]
      }
    }
  ]
}
