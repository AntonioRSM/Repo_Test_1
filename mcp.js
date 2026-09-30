// Aggiunge il server MCP f5-tts al mcp.json di LM Studio (~/.lmstudio/mcp.json)
module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: "python lmstudio_mcp_config.py --install"
      }
    },
    {
      method: "notify",
      params: { html: "Server MCP f5-tts installato. In LM Studio attivalo da Program > Integrations o riavvia LM Studio." }
    }
  ]
}
