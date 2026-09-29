// Rileva GPU/VRAM/RAM e scrive app/config.json con il modello F5-TTS più adatto
module.exports = {
  run: [
    {
      method: "input",
      params: {
        title: "Lingua principale dei testi",
        description: "it = modello italiano (alien79/F5-TTS-italian), en/zh = F5-TTS v1 Base ufficiale",
        form: [{ key: "lang", title: "Lingua (it / en / zh)", default: "it" }]
      }
    },
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: "python detect_hardware.py {{input.lang || 'it'}}"
      }
    }
  ]
}
