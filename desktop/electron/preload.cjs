// Minimal, typed bridge; the renderer talks to the engine over HTTP with the per-launch token.
const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("wsos", {
  engineInfo: () => ipcRenderer.invoke("engine:info"),
  engineLog: () => ipcRenderer.invoke("engine:log"),
  onEngineStatus: (listener) => {
    const handler = (_event, info) => listener(info);
    ipcRenderer.on("engine-status", handler);
    return () => ipcRenderer.removeListener("engine-status", handler);
  },
  pickFolders: () => ipcRenderer.invoke("dialog:pick-folders"),
  openPath: (target) => ipcRenderer.invoke("shell:open-path", target),
  showInFolder: (target) => ipcRenderer.invoke("shell:show-in-folder", target),
  setTitleBarSymbolColor: (color) => ipcRenderer.invoke("window:theme-overlay", color),
  // Absolute paths of dropped files (File.path was removed in Electron 32).
  pathForFile: (file) => webUtils.getPathForFile(file),
});
