module.exports = {
  requires: {
    bundle: "ai"
  },
  daemon: true,
  run: [
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        env: {
          PYTORCH_ENABLE_MPS_FALLBACK: 1
        },
        message: "python web_ui.py {{port}}",
        on: [{ event: "/http:\\/\\/\\S+/", done: true }]
      }
    },
    {
      method: "local.set",
      params: { url: "{{input.event[0]}}" }
    }
  ]
}
