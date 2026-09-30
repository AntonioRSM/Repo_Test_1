module.exports = {
  version: "3.7",
  title: "F5-TTS + LM Studio",
  description: "Testo → audio con F5-TTS scelto in base all'hardware, collegato all'LLM di LM Studio",
  menu: async (kernel, info) => {
    const installed = info.exists("app/env")
    const running = {
      install: info.running("install.js"),
      start: info.running("start.js"),
      update: info.running("update.js"),
      reset: info.running("reset.js")
    }
    if (running.install) {
      return [{ default: true, icon: "fa-solid fa-plug", text: "Installazione…", href: "install.js" }]
    }
    if (!installed) {
      return [{ default: true, icon: "fa-solid fa-plug", text: "Installa", href: "install.js" }]
    }
    if (running.start) {
      const local = info.local("start.js")
      const items = [{ icon: "fa-solid fa-terminal", text: "Terminale", href: "start.js" }]
      if (local && local.url) {
        items.unshift({ default: true, icon: "fa-solid fa-rocket", text: "Apri interfaccia", href: local.url })
      } else {
        items[0].default = true
      }
      return items
    }
    if (running.update) {
      return [{ default: true, icon: "fa-solid fa-terminal", text: "Aggiornamento…", href: "update.js" }]
    }
    if (running.reset) {
      return [{ default: true, icon: "fa-solid fa-terminal", text: "Reset…", href: "reset.js" }]
    }
    return [
      { default: true, icon: "fa-solid fa-power-off", text: "Avvia", href: "start.js" },
      { icon: "fa-solid fa-microchip", text: "Rileva hardware / cambia lingua", href: "detect.js" },
      { icon: "fa-solid fa-link", text: "Verifica LM Studio", href: "check.js" },
      { icon: "fa-solid fa-plug-circle-bolt", text: "Installa MCP in LM Studio", href: "mcp.js" },
      { icon: "fa-solid fa-bolt", text: "Accelerazione GPU AMD (ROCm)", href: "rocm.js" },
      { icon: "fa-solid fa-rotate", text: "Aggiorna", href: "update.js" },
      { icon: "fa-solid fa-plug", text: "Reinstalla", href: "install.js" },
      {
        icon: "fa-regular fa-circle-xmark",
        text: "<div><strong>Reset</strong><div>Torna allo stato pre-installazione</div></div>",
        href: "reset.js",
        confirm: "Vuoi davvero resettare l'app?"
      }
    ]
  }
}
