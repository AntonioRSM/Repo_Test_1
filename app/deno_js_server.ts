// Server MCP (stdio) per LM Studio con lo strumento `run_javascript`.
// A differenza della sandbox JavaScript integrata in LM Studio, lo script viene eseguito da Deno
// con i permessi passati a questo server (es. --allow-read=D:\Workspace --allow-write=D:\Workspace --allow-run).
//
// Avvio (lo scrive lmstudio_deno_config.py in ~/.lmstudio/mcp.json):
//   deno run --no-prompt --allow-run=<deno.exe> deno_js_server.ts --deno=<deno.exe> [permessi per gli script...]
// Gli argomenti dopo deno_js_server.ts che non iniziano con --deno= sono i permessi degli script.

const VERSION = "1.0.0";
const DEFAULT_TIMEOUT_MS = 120_000;
const MAX_OUTPUT = 100_000;

let denoPath = "deno";
const scriptFlags: string[] = [];
for (const arg of Deno.args) {
  if (arg.startsWith("--deno=")) denoPath = arg.slice("--deno=".length);
  else scriptFlags.push(arg);
}

const TOOL = {
  name: "run_javascript",
  description:
    "Esegue codice JavaScript/TypeScript con Deno e restituisce stdout, stderr e codice di uscita. " +
    "Usa console.log per stampare i risultati. Le API Deno (Deno.readTextFile, Deno.writeTextFile, " +
    "Deno.readDir, new Deno.Command(...)) sono disponibili entro questi permessi: " +
    (scriptFlags.join(" ") || "nessuno") + ". Nei percorsi Windows usa / oppure \\\\.",
  inputSchema: {
    type: "object",
    properties: {
      code: { type: "string", description: "Codice JavaScript o TypeScript da eseguire (top-level await consentito)." },
      timeout_ms: { type: "number", description: `Tempo massimo in millisecondi (default ${DEFAULT_TIMEOUT_MS}).` },
    },
    required: ["code"],
  },
};

const enc = new TextEncoder();
const dec = new TextDecoder();

function clip(text: string): string {
  return text.length > MAX_OUTPUT ? text.slice(0, MAX_OUTPUT) + `\n… (output troncato a ${MAX_OUTPUT} caratteri)` : text;
}

async function runJavascript(code: string, timeoutMs: number): Promise<{ text: string; isError: boolean }> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    // "-" = codice letto da stdin, nessun file temporaneo. --no-prompt: niente richieste interattive di permessi.
    const child = new Deno.Command(denoPath, {
      args: ["run", "--quiet", "--no-prompt", ...scriptFlags, "-"],
      stdin: "piped",
      stdout: "piped",
      stderr: "piped",
      env: { NO_COLOR: "1" },
      signal: abort.signal,
    }).spawn();
    const writer = child.stdin.getWriter();
    await writer.write(enc.encode(code));
    await writer.close();
    const out = await child.output();
    const parts = [];
    const stdout = dec.decode(out.stdout).trimEnd();
    const stderr = dec.decode(out.stderr).trimEnd();
    if (stdout) parts.push(`stdout:\n${stdout}`);
    if (stderr) parts.push(`stderr:\n${stderr}`);
    if (abort.signal.aborted) parts.push(`Interrotto: superato il tempo massimo di ${timeoutMs} ms.`);
    parts.push(`codice di uscita: ${out.code}`);
    return { text: clip(parts.join("\n\n")), isError: !out.success };
  } catch (e) {
    return { text: `Impossibile avviare Deno (${denoPath}): ${e instanceof Error ? e.message : e}`, isError: true };
  } finally {
    clearTimeout(timer);
  }
}

async function handle(msg: { id?: number | string; method?: string; params?: Record<string, unknown> }) {
  switch (msg.method) {
    case "initialize":
      return {
        protocolVersion: (msg.params?.protocolVersion as string) ?? "2025-06-18",
        capabilities: { tools: {} },
        serverInfo: { name: "deno-js", version: VERSION },
      };
    case "ping":
      return {};
    case "tools/list":
      return { tools: [TOOL] };
    case "tools/call": {
      const name = msg.params?.name;
      const args = (msg.params?.arguments ?? {}) as { code?: unknown; timeout_ms?: unknown };
      if (name !== TOOL.name) throw { code: -32602, message: `Strumento sconosciuto: ${name}` };
      if (typeof args.code !== "string" || !args.code.trim()) {
        return { content: [{ type: "text", text: "Parametro 'code' mancante." }], isError: true };
      }
      const timeout = typeof args.timeout_ms === "number" && args.timeout_ms > 0 ? args.timeout_ms : DEFAULT_TIMEOUT_MS;
      const result = await runJavascript(args.code, timeout);
      return { content: [{ type: "text", text: result.text }], isError: result.isError };
    }
    default:
      throw { code: -32601, message: `Metodo non supportato: ${msg.method}` };
  }
}

function send(obj: unknown) {
  Deno.stdout.writeSync(enc.encode(JSON.stringify(obj) + "\n"));
}

async function serve(raw: string) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "JSON non valido" } });
    return;
  }
  if (msg.id === undefined || msg.id === null) return; // notifiche (es. notifications/initialized)
  try {
    send({ jsonrpc: "2.0", id: msg.id, result: await handle(msg) });
  } catch (e) {
    const err = e as { code?: number; message?: string };
    send({ jsonrpc: "2.0", id: msg.id, error: { code: err.code ?? -32603, message: err.message ?? String(e) } });
  }
}

// Messaggi JSON-RPC separati da a capo (trasporto stdio MCP); le chiamate girano in parallelo.
let buffer = "";
for await (const chunk of Deno.stdin.readable) {
  buffer += dec.decode(chunk, { stream: true });
  let nl;
  while ((nl = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, nl).trim();
    buffer = buffer.slice(nl + 1);
    if (line) serve(line);
  }
}
