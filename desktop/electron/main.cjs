// Electron main process: owns the engine process, the tray and the window.
const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage, shell, Notification } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const APP_ID = "ai.workspaceos.ragvaultstudio";
const ENGINE_DIR = process.env.WSOS_ENGINE_DIR || path.resolve(__dirname, "..", "..", "engine");
const PYTHON = path.join(ENGINE_DIR, ".venv", "Scripts", "python.exe");
const ICON = path.join(__dirname, "..", "assets", "icon.png");
const TRAY_ICON = path.join(__dirname, "..", "assets", "tray.png");
const START_HIDDEN = process.argv.includes("--hidden");

let mainWindow = null;
let tray = null;
let engine = null;
let quitting = false;
const engineInfo = { port: null, token: crypto.randomBytes(24).toString("hex"), error: null, log: [] };

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => showWindow());
}
app.setAppUserModelId(APP_ID);

// ------------------------------------------------------------------ engine

function startEngine() {
  return new Promise((resolve) => {
    if (!fs.existsSync(PYTHON)) {
      engineInfo.error = `Python environment not found at ${PYTHON}. Run "uv sync" in the engine folder.`;
      resolve();
      return;
    }
    engine = spawn(PYTHON, ["-m", "vault_engine", "--port", "0", "--log-level", "warning"], {
      cwd: ENGINE_DIR,
      env: { ...process.env, WSOS_TOKEN: engineInfo.token, WSOS_PARENT_PID: String(process.pid), PYTHONUTF8: "1" },
      windowsHide: true,
    });
    const remember = (chunk) => {
      engineInfo.log.push(...chunk.toString("utf8").split(/\r?\n/).filter(Boolean));
      engineInfo.log = engineInfo.log.slice(-200);
    };
    let buffered = "";
    engine.stdout.on("data", (chunk) => {
      remember(chunk);
      buffered += chunk.toString("utf8");
      const match = buffered.match(/VAULT_ENGINE_PORT=(\d+)/);
      if (match && !engineInfo.port) {
        engineInfo.port = Number(match[1]);
        waitForHealth().then(resolve);
      }
    });
    engine.stderr.on("data", remember);
    engine.on("exit", (code) => {
      if (!quitting) {
        engineInfo.error = `Engine exited with code ${code}`;
        mainWindow?.webContents.send("engine-status", { ...engineInfo });
      }
      resolve();
    });
  });
}

async function waitForHealth() {
  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${engineInfo.port}/health`);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  engineInfo.error = "Engine did not become healthy in time";
}

async function engineFetch(route, init = {}) {
  if (!engineInfo.port) throw new Error("engine not running");
  const res = await fetch(`http://127.0.0.1:${engineInfo.port}${route}`, {
    ...init,
    headers: { "content-type": "application/json", "x-wsos-token": engineInfo.token, ...(init.headers || {}) },
  });
  if (!res.ok) throw new Error(`${route}: ${res.status}`);
  return res.json();
}

// ------------------------------------------------------------------ window & tray

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 960,
    minHeight: 600,
    show: false,
    title: "RAG Vault Studio",
    icon: ICON,
    backgroundColor: "#00000000",
    backgroundMaterial: "mica", // Windows 11 22H2+; ignored elsewhere
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#00000000", symbolColor: "#808080", height: 40 },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });

  const devUrl = process.env.WSOS_DEV_URL;
  if (devUrl) mainWindow.loadURL(devUrl);
  else mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));

  mainWindow.once("ready-to-show", () => {
    if (!START_HIDDEN) mainWindow.show();
  });
  // Closing hides to the tray so folder watching keeps running.
  mainWindow.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      mainWindow.hide();
      if (!app.__trayHintShown && Notification.isSupported()) {
        app.__trayHintShown = true;
        new Notification({ title: "RAG Vault Studio", body: "Continua a sincronizzare i Vault dalla tray di sistema." }).show();
      }
    }
  });
  // Never navigate the app window away; open links in the default browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!devUrl || !url.startsWith(devUrl)) event.preventDefault();
  });
}

function showWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

async function syncAll() {
  try {
    const vaults = await engineFetch("/vaults");
    await Promise.all(vaults.map((v) => engineFetch(`/vaults/${v.id}/sync`, { method: "POST" })));
  } catch (err) {
    dialog.showErrorBox("Sincronizzazione", String(err));
  }
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(TRAY_ICON));
  tray.setToolTip("RAG Vault Studio");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Apri RAG Vault Studio", click: showWindow },
      { label: "Sincronizza tutti i Vault", click: syncAll },
      { type: "separator" },
      {
        label: "Avvia con Windows",
        type: "checkbox",
        checked: app.getLoginItemSettings().openAtLogin,
        // Unpackaged, electron.exe needs the app folder as its first argument.
        click: (item) =>
          app.setLoginItemSettings({
            openAtLogin: item.checked,
            args: app.isPackaged ? ["--hidden"] : [app.getAppPath(), "--hidden"],
          }),
      },
      { type: "separator" },
      { label: "Esci", click: () => { quitting = true; app.quit(); } },
    ]),
  );
  tray.on("click", showWindow);
}

// ------------------------------------------------------------------ IPC

ipcMain.handle("engine:info", () => ({ port: engineInfo.port, token: engineInfo.token, error: engineInfo.error }));
ipcMain.handle("engine:log", () => engineInfo.log.slice(-100));
ipcMain.handle("dialog:pick-folders", async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory", "multiSelections"] });
  return result.canceled ? [] : result.filePaths;
});
// Only files inside a Vault's source folders may be opened: the renderer can be
// fed arbitrary paths (prompt injection, corrupted state) and shell.openPath on an
// executable would run it.
let supportedExtsPromise = null;
function supportedExtensions() {
  // The engine exposes its document types on /health (SUPPORTED_EXTS): only those may
  // be OPENED — an .exe/.bat/.cmd/.js/.lnk/.url inside a source folder would otherwise
  // be executed by shell.openPath (Miglioramento #8).
  supportedExtsPromise ??= engineFetch("/health").then(
    (h) => new Set((h.supported_extensions ?? []).map((e) => String(e).toLowerCase())),
  );
  return supportedExtsPromise;
}

async function assertOpenableTarget(target, { forOpen = false } = {}) {
  let resolved;
  try {
    // realpath follows symlinks/junctions: a link inside a Vault source must not
    // silently point outside it (Miglioramento #8).
    resolved = fs.realpathSync(path.resolve(String(target)));
  } catch {
    return null; // must exist
  }
  let stat;
  try {
    stat = fs.statSync(resolved);
  } catch {
    return null;
  }
  if (!stat.isFile()) return null;
  let vaults, exts;
  try {
    [vaults, exts] = await Promise.all([engineFetch("/vaults"), forOpen ? supportedExtensions() : Promise.resolve(null)]);
  } catch {
    return null; // engine unreachable: deny rather than guess
  }
  const normalized = resolved.toLowerCase();
  const inside = (vaults ?? []).some((v) =>
    (v.sources ?? []).some((s) => {
      let root;
      try {
        root = fs.realpathSync(path.resolve(String(s))).toLowerCase();
      } catch {
        root = path.resolve(String(s)).toLowerCase();
      }
      return normalized === root || normalized.startsWith(root + path.sep);
    }),
  );
  if (!inside) return null;
  // For unsupported types the UI keeps only "mostra nella cartella" (no execution).
  if (forOpen && (!(exts instanceof Set) || !exts.has(path.extname(resolved).toLowerCase()))) return null;
  return resolved;
}

ipcMain.handle("shell:open-path", async (_e, target) => {
  const safe = await assertOpenableTarget(target, { forOpen: true });
  if (!safe) throw new Error("apertura consentita solo per i documenti supportati dei Vault");
  return shell.openPath(safe);
});
ipcMain.handle("shell:show-in-folder", async (_e, target) => {
  const safe = await assertOpenableTarget(target);
  if (!safe) throw new Error("apertura consentita solo per i documenti dei Vault");
  shell.showItemInFolder(safe);
});
ipcMain.handle("window:theme-overlay", (_e, symbolColor) => {
  try {
    mainWindow?.setTitleBarOverlay({ color: "#00000000", symbolColor: String(symbolColor), height: 40 });
  } catch {
    /* overlay unsupported */
  }
});

// ------------------------------------------------------------------ lifecycle

app.whenReady().then(async () => {
  createTray();
  createWindow();
  await startEngine();
  mainWindow?.webContents.send("engine-status", { port: engineInfo.port, token: engineInfo.token, error: engineInfo.error });
});

app.on("before-quit", () => {
  quitting = true;
  if (engine && engine.exitCode === null) {
    // The venv python.exe is a launcher with a child interpreter; kill the whole tree.
    spawnSync("taskkill", ["/pid", String(engine.pid), "/T", "/F"], { windowsHide: true });
  }
});

app.on("window-all-closed", () => {
  /* stay alive in the tray */
});
