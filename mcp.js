// Stampa la configurazione da incollare nel mcp.json di LM Studio
module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: "python lmstudio_mcp_config.py"
      }
    }
  ]
}
