import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  CardHeader,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  makeStyles,
  MessageBar,
  MessageBarBody,
  Radio,
  RadioGroup,
  SpinButton,
  Subtitle2,
  Switch,
  Text,
  Textarea,
  tokens,
} from "@fluentui/react-components";
import { AddRegular, ArrowSyncRegular, DeleteRegular, DocumentTextRegular, EditRegular, PlugConnectedRegular, PlugDisconnectedRegular } from "@fluentui/react-icons";
import { useCallback, useEffect, useState } from "react";
import { api, SECRET_MASK, type McpServer, type McpServerInput } from "../api";
import { useStore } from "../store";

const useStyles = makeStyles({
  list: { display: "grid", gap: "10px" },
  tools: { display: "flex", flexWrap: "wrap", gap: "6px" },
  form: { display: "grid", gap: "12px" },
  row: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" },
  log: { fontFamily: "Cascadia Code, Consolas, monospace", fontSize: "12px", whiteSpace: "pre-wrap", maxHeight: "320px", overflow: "auto", background: tokens.colorNeutralBackground3, padding: "8px", borderRadius: tokens.borderRadiusMedium },
});

const STATUS: Record<McpServer["status"], { label: string; color: "success" | "warning" | "danger" | "subtle" }> = {
  connected: { label: "Connesso", color: "success" },
  connecting: { label: "Connessione…", color: "warning" },
  error: { label: "Errore", color: "danger" },
  disabled: { label: "Disattivato", color: "subtle" },
};

// "KEY=value" lines <-> object; masked values stay masked so the engine keeps the stored secret.
const toLines = (obj: Record<string, string>, sep: string) => Object.entries(obj).map(([k, v]) => `${k}${sep}${v}`).join("\n");
const fromLines = (text: string, sep: string) =>
  Object.fromEntries(
    text
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        const i = l.indexOf(sep);
        return i < 0 ? [l, ""] : [l.slice(0, i).trim(), l.slice(i + sep.length).trim()];
      }),
  );

/** Splits a command line into arguments, honouring double quotes (Windows paths with spaces). */
function splitArgs(text: string): string[] {
  return [...text.matchAll(/"([^"]*)"|(\S+)/g)].map((m) => m[1] ?? m[2]);
}
const joinArgs = (args: string[]) => args.map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(" ");

const EMPTY: McpServerInput = { name: "", transport: "stdio", command: "", args: [], cwd: null, url: "", env: {}, headers: {}, enabled: true, timeout_seconds: 120 };

export function McpServers() {
  const styles = useStyles();
  const { notify } = useStore();
  const [servers, setServers] = useState<McpServer[]>([]);
  const [editing, setEditing] = useState<McpServer | "new" | null>(null);
  const [log, setLog] = useState<{ name: string; lines: string[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => setServers(await api.mcpServers()), []);
  useEffect(() => {
    load();
  }, [load]);

  async function act(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    try {
      await fn();
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(null);
      load();
    }
  }

  const totalTools = servers.filter((s) => s.status === "connected").reduce((n, s) => n + s.tools.length, 0);

  return (
    <Card style={{ display: "grid", gap: 12, maxWidth: 820, marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Subtitle2>Server MCP</Subtitle2>
        <Button icon={<AddRegular />} onClick={() => setEditing("new")}>Aggiungi server</Button>
      </div>
      <Caption1>
        Gli strumenti dei server connessi diventano strumenti dell'agente (ogni chiamata chiede approvazione). Ogni strumento allunga il prompt:
        con un modello locale tieni attivi solo i server che ti servono. Attivi ora: {totalTools} strumenti.
      </Caption1>
      <div className={styles.list}>
        {servers.length === 0 && <Body1>Nessun server configurato.</Body1>}
        {servers.map((s) => (
          <Card key={s.id} appearance="outline">
            <CardHeader
              image={s.status === "connected" ? <PlugConnectedRegular fontSize={22} /> : <PlugDisconnectedRegular fontSize={22} />}
              header={<Text weight="semibold">{s.name}</Text>}
              description={
                <Caption1 truncate wrap={false} title={s.transport === "http" ? s.url : `${s.command} ${joinArgs(s.args)}`}>
                  {s.transport === "http" ? `HTTP · ${s.url}` : `stdio · ${s.command} ${joinArgs(s.args)}`}
                  {s.server_info?.name ? ` · ${s.server_info.name} ${s.server_info.version ?? ""}` : ""}
                </Caption1>
              }
              action={<Badge color={STATUS[s.status].color}>{STATUS[s.status].label}</Badge>}
            />
            {s.error && (
              <MessageBar intent="error">
                <MessageBarBody>{s.error}</MessageBarBody>
              </MessageBar>
            )}
            {s.tools.length > 0 && (
              <div className={styles.tools}>
                {s.tools.map((t) => (
                  <Badge key={t.name} appearance="outline" title={t.description}>{t.original_name}</Badge>
                ))}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Switch
                checked={s.enabled}
                disabled={busy === s.id}
                label="Attivo"
                onChange={(_, d) => act(s.id, () => api.updateMcpServer(s.id, { enabled: d.checked }))}
              />
              <Button size="small" icon={<ArrowSyncRegular />} disabled={!s.enabled || busy === s.id} onClick={() => act(s.id, () => api.reconnectMcpServer(s.id))}>
                Riconnetti
              </Button>
              <Button size="small" icon={<EditRegular />} onClick={() => setEditing(s)}>Modifica</Button>
              {s.transport === "stdio" && (
                <Button size="small" icon={<DocumentTextRegular />} onClick={async () => setLog({ name: s.name, lines: (await api.mcpLog(s.id)).lines })}>
                  Log
                </Button>
              )}
              <Button
                size="small"
                icon={<DeleteRegular />}
                onClick={() => confirm(`Rimuovere il server MCP "${s.name}"?`) && act(s.id, () => api.removeMcpServer(s.id))}
              >
                Rimuovi
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {editing && (
        <ServerDialog
          server={editing === "new" ? null : editing}
          onClose={(saved) => {
            setEditing(null);
            if (saved) {
              notify(saved.status === "connected" ? `"${saved.name}" connesso: ${saved.tools.length} strumenti` : `"${saved.name}" salvato (${STATUS[saved.status].label.toLowerCase()})`, saved.status === "error" ? "error" : "success");
              load();
            }
          }}
        />
      )}
      <Dialog open={!!log} onOpenChange={(_, d) => !d.open && setLog(null)}>
        <DialogSurface style={{ maxWidth: 820 }}>
          <DialogBody>
            <DialogTitle>Log di {log?.name} (stderr)</DialogTitle>
            <DialogContent>
              <div className={styles.log}>{log?.lines.join("\n") || "(vuoto)"}</div>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setLog(null)}>Chiudi</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </Card>
  );
}

function ServerDialog({ server, onClose }: { server: McpServer | null; onClose: (saved?: McpServer) => void }) {
  const styles = useStyles();
  const [form, setForm] = useState<McpServerInput>(server ? { ...server } : EMPTY);
  const [argsText, setArgsText] = useState(server ? joinArgs(server.args) : "");
  const [envText, setEnvText] = useState(server ? toLines(server.env, "=") : "");
  const [headersText, setHeadersText] = useState(server ? toLines(server.headers, ": ") : "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<McpServerInput>) => setForm({ ...form, ...patch });

  async function save() {
    setSaving(true);
    setError(null);
    const body: McpServerInput = {
      ...form,
      args: splitArgs(argsText),
      env: fromLines(envText, "="),
      headers: fromLines(headersText, ":"),
      cwd: form.cwd || null,
    };
    try {
      onClose(server ? await api.updateMcpServer(server.id, body) : await api.addMcpServer(body));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface style={{ maxWidth: 680 }}>
        <DialogBody>
          <DialogTitle>{server ? `Modifica ${server.name}` : "Nuovo server MCP"}</DialogTitle>
          <DialogContent className={styles.form}>
            <div className={styles.row}>
              <Field label="Nome" required hint="Diventa parte del nome degli strumenti: mcp__nome__strumento">
                <Input value={form.name} onChange={(_, d) => set({ name: d.value })} placeholder="es. filesystem" />
              </Field>
              <Field label="Trasporto">
                <RadioGroup layout="horizontal" value={form.transport} onChange={(_, d) => set({ transport: d.value as "stdio" })}>
                  <Radio value="stdio" label="Locale (stdio)" />
                  <Radio value="http" label="HTTP" />
                </RadioGroup>
              </Field>
            </div>
            {form.transport === "stdio" ? (
              <>
                <div className={styles.row}>
                  <Field label="Comando" required hint="es. npx, uvx, node, python o percorso completo">
                    <Input value={form.command} onChange={(_, d) => set({ command: d.value })} placeholder="npx" />
                  </Field>
                  <Field label="Cartella di lavoro">
                    <Input value={form.cwd ?? ""} onChange={(_, d) => set({ cwd: d.value })} placeholder="(facoltativa)" />
                  </Field>
                </div>
                <Field label="Argomenti" hint='Separati da spazi; usa le virgolette per i percorsi con spazi'>
                  <Input value={argsText} onChange={(_, d) => setArgsText(d.value)} placeholder='-y @modelcontextprotocol/server-filesystem "C:\Users\me\Documents"' />
                </Field>
                <Field label="Variabili d'ambiente" hint={`Una per riga, NOME=valore. Salvate cifrate (DPAPI); ${SECRET_MASK} = valore invariato`}>
                  <Textarea value={envText} onChange={(_, d) => setEnvText(d.value)} placeholder="GITHUB_TOKEN=..." resize="vertical" />
                </Field>
              </>
            ) : (
              <>
                <Field label="URL" required hint="Endpoint Streamable HTTP, es. http://localhost:8000/mcp">
                  <Input value={form.url} onChange={(_, d) => set({ url: d.value })} />
                </Field>
                <Field label="Header" hint={`Una per riga, Nome: valore (es. Authorization: Bearer …). Salvati cifrati; ${SECRET_MASK} = invariato`}>
                  <Textarea value={headersText} onChange={(_, d) => setHeadersText(d.value)} resize="vertical" />
                </Field>
              </>
            )}
            <div className={styles.row}>
              <Field label="Timeout chiamata (secondi)">
                <SpinButton value={form.timeout_seconds} min={5} max={1800} onChange={(_, d) => set({ timeout_seconds: d.value ?? (Number(d.displayValue) || 120) })} />
              </Field>
              <Switch checked={form.enabled} onChange={(_, d) => set({ enabled: d.checked })} label="Attivo" />
            </div>
            {error && (
              <MessageBar intent="error">
                <MessageBarBody>{error}</MessageBarBody>
              </MessageBar>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => onClose()}>Annulla</Button>
            <Button appearance="primary" disabled={saving || !form.name.trim() || (form.transport === "stdio" ? !form.command.trim() : !form.url.trim())} onClick={save}>
              {saving ? "Connessione…" : "Salva e connetti"}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
