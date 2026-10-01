// Aggiunge a LM Studio (~/.lmstudio/mcp.json) il server MCP deno-js: run_javascript con accesso al filesystem
module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: "python lmstudio_deno_config.py --install --allow-read \"D:\\Workspace,C:\\pinokio\\api\\Repo_Test_1.git\" --allow-write \"D:\\Workspace\" --allow-run"
      }
    },
    {
      method: "notify",
      params: { html: "Server MCP deno-js installato. In LM Studio attiva 'mcp/deno-js' da Program > Integrations (o riavvia LM Studio)." }
    }
  ]
}
