import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  Dropdown,
  makeStyles,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Text,
  Textarea,
  tokens,
  Tooltip,
} from "@fluentui/react-components";
import {
  AddRegular,
  BotRegular,
  CheckmarkCircleRegular,
  CheckmarkRegular,
  ChevronDownRegular,
  ChevronRightRegular,
  CircleRegular,
  DeleteRegular,
  DismissCircleRegular,
  DismissRegular,
  SendRegular,
  ShieldCheckmarkRegular,
  StopRegular,
} from "@fluentui/react-icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, modelLabel, type AgentMessage, type AgentThread, type ModelRef, type PendingCall } from "../api";
import { Markdown } from "../components/Markdown";
import { useModels, useStore } from "../store";

const TOOL_LABEL: Record<string, string> = {
  vault_search: "Ricerca nei Vault",
  list_vaults: "Elenco Vault",
  list_directory: "Elenco cartella",
  read_file: "Lettura file",
  write_file: "Scrittura file",
  edit_file: "Modifica file",
  run_powershell: "Comando PowerShell",
  web_search: "Ricerca web",
  fetch_url: "Lettura pagina web",
  task_list: "Piano di lavoro",
};
const RISK_COLOR: Record<string, "informative" | "warning" | "danger" | "important" | "subtle"> = {
  read: "informative",
  network: "important",
  write: "warning",
  execute: "danger",
  plan: "subtle",
};

const useStyles = makeStyles({
  layout: { display: "grid", gridTemplateColumns: "250px minmax(0, 1fr)", gap: "16px", height: "calc(100vh - 100px)" },
  sidebar: { display: "flex", flexDirection: "column", gap: "6px", overflow: "auto" },
  threadItem: {
    padding: "8px 10px",
    borderRadius: tokens.borderRadiusMedium,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
  },
  active: { backgroundColor: tokens.colorNeutralBackground1Selected },
  main: { display: "flex", flexDirection: "column", minHeight: 0 },
  toolbar: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", paddingBottom: "8px", borderBottom: `1px solid ${tokens.colorNeutralStroke2}` },
  scroll: { flex: 1, overflow: "auto", padding: "12px 4px", display: "flex", flexDirection: "column", gap: "12px" },
  user: { alignSelf: "flex-end", maxWidth: "75%", background: tokens.colorBrandBackground2, padding: "8px 12px", borderRadius: "12px 12px 2px 12px", whiteSpace: "pre-wrap" },
  assistant: { maxWidth: "92%" },
  tool: { padding: "8px 12px", borderLeft: `3px solid ${tokens.colorNeutralStroke1}`, background: tokens.colorNeutralBackground2, borderRadius: tokens.borderRadiusMedium },
  args: { fontFamily: "Cascadia Code, Consolas, monospace", fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-word", margin: "6px 0" },
  composer: { display: "flex", gap: "8px", alignItems: "flex-end", paddingTop: "8px", borderTop: `1px solid ${tokens.colorNeutralStroke2}` },
  tasks: { padding: "8px 12px", marginBottom: "8px" },
});

function parseArgs(raw: string | Record<string, unknown>): Record<string, unknown> {
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return { raw };
  }
}

function summarize(args: Record<string, unknown>): string {
  const pick = args.command ?? args.query ?? args.path ?? args.url;
  return typeof pick === "string" ? pick : "";
}

export default function AgentPage() {
  const styles = useStyles();
  const { vaults, settings, onAgentEvent, notify } = useStore();
  const llms = useModels("llm");
  const [threads, setThreads] = useState<AgentThread[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [thread, setThread] = useState<AgentThread | null>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [streaming, setStreaming] = useState("");
  const [pending, setPending] = useState<PendingCall[]>([]);
  const [runningTool, setRunningTool] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(0);
  const [input, setInput] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const loadThreads = useCallback(async () => setThreads(await api.threads()), []);

  const loadThread = useCallback(async (id: string) => {
    const t = await api.thread(id);
    setThread(t);
    setMessages(t.messages ?? []);
    setRunning(t.status.running);
    setStep(t.status.step ?? 0);
    setPending(t.status.pending.map((p) => ({ ...p, arguments: parseArgs(p.arguments) })));
    setStreaming("");
  }, []);

  useEffect(() => {
    loadThreads().then(() => undefined);
  }, [loadThreads]);
  useEffect(() => {
    if (!currentId && threads.length) setCurrentId(threads[0].id);
  }, [threads, currentId]);
  useEffect(() => {
    if (currentId) loadThread(currentId);
  }, [currentId, loadThread]);

  useEffect(
    () =>
      onAgentEvent((e) => {
        if (e.thread_id !== currentId) {
          if (e.kind === "run_finished") loadThreads();
          return;
        }
        switch (e.kind) {
          case "run_started":
            setRunning(true);
            break;
          case "thinking":
            setStep(e.step);
            setStreaming("");
            break;
          case "delta":
            setStreaming((s) => s + e.text);
            break;
          case "message":
            setMessages((prev) => (prev.some((m) => m.id === e.message.id) ? prev : [...prev, e.message]));
            if (e.message.role === "assistant") setStreaming("");
            if (e.message.role === "tool") setRunningTool(null);
            break;
          case "approval":
            setPending((p) => [...p, e.call]);
            break;
          case "approval_resolved":
            setPending((p) => p.filter((c) => c.id !== e.call_id));
            break;
          case "tool_started":
            setRunningTool(e.call_id);
            break;
          case "run_finished":
            setRunning(false);
            setStreaming("");
            setPending([]);
            setRunningTool(null);
            if (e.error) notify(`Agente: ${e.error}`, "error");
            loadThread(e.thread_id);
            loadThreads();
            break;
        }
      }),
    [onAgentEvent, currentId, loadThread, loadThreads, notify],
  );

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streaming, pending.length]);

  const results = useMemo(() => new Map(messages.filter((m) => m.role === "tool").map((m) => [m.tool_call_id, m])), [messages]);

  async function newThread() {
    const t = await api.createThread({ model: settings?.llm ?? null });
    await loadThreads();
    setCurrentId(t.id);
  }

  async function send() {
    const text = input.trim();
    if (!text) return;
    let id = currentId;
    if (!id) {
      const t = await api.createThread({ model: settings?.llm ?? null });
      id = t.id;
      setCurrentId(id);
    }
    setInput("");
    try {
      await api.sendMessage(id, text);
      setRunning(true);
      loadThreads();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  }

  async function patchThread(patch: Parameters<typeof api.updateThread>[1]) {
    if (!thread) return;
    setThread(await api.updateThread(thread.id, patch));
  }

  const model: ModelRef | null = thread?.model ?? settings?.llm ?? null;
  const modelKey = model ? `${model.provider}::${model.model}` : "";
  const selectedVaults = thread?.vault_ids ?? [];

  return (
    <div className={styles.layout}>
      <div className={styles.sidebar}>
        <Button appearance="primary" icon={<AddRegular />} onClick={newThread}>Nuova conversazione</Button>
        {threads.map((t) => (
          <div key={t.id} className={`${styles.threadItem} ${t.id === currentId ? styles.active : ""}`} onClick={() => setCurrentId(t.id)}>
            {t.status.running ? <Spinner size="extra-tiny" /> : <BotRegular />}
            <Text truncate wrap={false} style={{ flex: 1 }} title={t.title}>{t.title}</Text>
            <Button
              size="small"
              appearance="subtle"
              icon={<DeleteRegular />}
              aria-label="Elimina conversazione"
              onClick={async (ev) => {
                ev.stopPropagation();
                await api.deleteThread(t.id);
                if (t.id === currentId) {
                  setCurrentId(null);
                  setThread(null);
                  setMessages([]);
                }
                loadThreads();
              }}
            />
          </div>
        ))}
      </div>

      <div className={styles.main}>
        <div className={styles.toolbar}>
          <Dropdown
            size="small"
            value={model ? modelLabel(model) : "Nessun LLM"}
            selectedOptions={[modelKey]}
            disabled={!thread}
            onOptionSelect={(_, d) => {
              const [provider, ...rest] = (d.optionValue ?? "").split("::");
              patchThread({ model: { provider: provider as ModelRef["provider"], model: rest.join("::") } });
            }}
            style={{ minWidth: 260 }}
          >
            {llms.map((m) => (
              <Option key={`${m.provider}::${m.model}`} value={`${m.provider}::${m.model}`} text={modelLabel(m)}>{modelLabel(m)}</Option>
            ))}
          </Dropdown>
          <Dropdown
            size="small"
            multiselect
            disabled={!thread}
            placeholder="Tutti i Vault"
            value={selectedVaults.length ? vaults.filter((v) => selectedVaults.includes(v.id)).map((v) => v.name).join(", ") : "Tutti i Vault"}
            selectedOptions={selectedVaults}
            onOptionSelect={(_, d) => patchThread({ vault_ids: d.selectedOptions })}
            style={{ minWidth: 220 }}
          >
            {vaults.map((v) => (
              <Option key={v.id} value={v.id}>{v.name}</Option>
            ))}
          </Dropdown>
          {thread && thread.auto_approve.length > 0 && (
            <Tooltip content="Strumenti che non chiedono più conferma in questa conversazione. Clic per revocare." relationship="description">
              <Badge appearance="tint" color="warning" icon={<ShieldCheckmarkRegular />} style={{ cursor: "pointer" }} onClick={() => patchThread({ auto_approve: [] })}>
                Sempre consentiti: {thread.auto_approve.map((n) => TOOL_LABEL[n] ?? n).join(", ")}
              </Badge>
            </Tooltip>
          )}
          <div style={{ flex: 1 }} />
          {running && <Caption1>Passo {step}…</Caption1>}
        </div>

        <div className={styles.scroll}>
          {!thread && (
            <div style={{ margin: "auto", textAlign: "center", maxWidth: 520 }}>
              <BotRegular fontSize={48} />
              <Text as="h2" size={500} weight="semibold" block>Agente locale</Text>
              <Body1>
                Fai una domanda sui tuoi documenti, chiedi di cercare sul web, leggere o creare file o eseguire comandi. Il modello gira su
                questo PC e ogni azione ti viene mostrata per l'approvazione prima di essere eseguita.
              </Body1>
            </div>
          )}
          {thread && thread.tasks.length > 0 && (
            <Card className={styles.tasks}>
              <Text weight="semibold">Piano</Text>
              {thread.tasks.map((t) => (
                <Caption1 key={t.id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {t.status === "completed" ? <CheckmarkCircleRegular /> : t.status === "in_progress" ? <Spinner size="extra-tiny" /> : <CircleRegular />}
                  {t.content}
                </Caption1>
              ))}
            </Card>
          )}
          {messages.map((m) => {
            if (m.role === "user") return <div key={m.id} className={styles.user}>{m.content}</div>;
            if (m.role === "tool") return null;
            const error = m.meta.error as string | undefined;
            return (
              <div key={m.id} className={styles.assistant}>
                {m.content && <Markdown text={m.content} />}
                {error && (
                  <MessageBar intent="error">
                    <MessageBarBody>{error}</MessageBarBody>
                  </MessageBar>
                )}
                {m.tool_calls?.map((c) => (
                  <ToolCard
                    key={c.id}
                    name={c.name}
                    args={parseArgs(c.arguments)}
                    result={results.get(c.id)}
                    pending={pending.some((p) => p.id === c.id)}
                    executing={runningTool === c.id}
                    onDecide={(decision) => thread && api.approve(thread.id, c.id, decision)}
                  />
                ))}
              </div>
            );
          })}
          {running && streaming && (
            <div className={styles.assistant}>
              <Markdown text={streaming} />
            </div>
          )}
          {running && !streaming && pending.length === 0 && !runningTool && (
            <Spinner size="tiny" label="Il modello locale sta elaborando…" labelPosition="after" style={{ justifyContent: "flex-start" }} />
          )}
          {/* Approvals requested before their assistant message reached the UI. */}
          {pending
            .filter((p) => !messages.some((m) => m.tool_calls?.some((c) => c.id === p.id)))
            .map((p) => (
              <ToolCard key={p.id} name={p.name} args={parseArgs(p.arguments)} pending executing={false} onDecide={(d) => thread && api.approve(thread.id, p.id, d)} />
            ))}
          <div ref={bottom} />
        </div>

        <div className={styles.composer}>
          <Textarea
            style={{ flex: 1 }}
            resize="vertical"
            value={input}
            placeholder={settings?.llm ? "Scrivi un messaggio… (Invio per inviare, Maiusc+Invio per andare a capo)" : "Configura un LLM in Impostazioni per usare l'agente"}
            onChange={(_, d) => setInput(d.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (!running) send();
              }
            }}
          />
          {running ? (
            <Button icon={<StopRegular />} onClick={() => thread && api.cancelRun(thread.id)}>Interrompi</Button>
          ) : (
            <Button appearance="primary" icon={<SendRegular />} disabled={!input.trim() || !model} onClick={send}>Invia</Button>
          )}
        </div>
      </div>
    </div>
  );
}

function ToolCard({
  name,
  args,
  result,
  pending,
  executing,
  onDecide,
}: {
  name: string;
  args: Record<string, unknown>;
  result?: AgentMessage;
  pending: boolean;
  executing: boolean;
  onDecide: (d: "allow" | "allow_always" | "deny") => void;
}) {
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  const meta = result?.meta ?? {};
  const denied = meta.decision === "deny";
  const failed = meta.ok === false && !denied;
  const risk = (meta.risk as string) ?? ({ write_file: "write", edit_file: "write", run_powershell: "execute", web_search: "network", fetch_url: "network", task_list: "plan" } as Record<string, string>)[name] ?? "read";
  const summary = summarize(args);
  const big = name === "write_file" || name === "run_powershell" || name === "edit_file";

  return (
    <div className={styles.tool} style={{ marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", cursor: result ? "pointer" : undefined }} onClick={() => result && setOpen(!open)}>
        {result ? (open ? <ChevronDownRegular /> : <ChevronRightRegular />) : null}
        <Badge appearance="tint" color={RISK_COLOR[risk] ?? "informative"}>{TOOL_LABEL[name] ?? name}</Badge>
        <Caption1 truncate wrap={false} style={{ flex: 1 }} title={summary}>{summary}</Caption1>
        {executing && <Spinner size="extra-tiny" label="in esecuzione" />}
        {result && !denied && !failed && <CheckmarkCircleRegular color={tokens.colorPaletteGreenForeground1} />}
        {denied && <Badge color="danger" appearance="tint">negato</Badge>}
        {failed && <DismissCircleRegular color={tokens.colorPaletteRedForeground1} />}
        {typeof meta.seconds === "number" && <Caption1>{meta.seconds as number}s</Caption1>}
      </div>
      {(pending || open || (big && !result)) && (
        <div className={styles.args}>
          {name === "run_powershell" ? String(args.command ?? "") :
           name === "write_file" ? `${args.path}\n\n${String(args.content ?? "").slice(0, 3000)}` :
           JSON.stringify(args, null, 2)}
        </div>
      )}
      {pending && (
        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <Button size="small" appearance="primary" icon={<CheckmarkRegular />} onClick={() => onDecide("allow")}>Consenti</Button>
          <Button size="small" icon={<ShieldCheckmarkRegular />} onClick={() => onDecide("allow_always")}>Consenti sempre in questa chat</Button>
          <Button size="small" icon={<DismissRegular />} onClick={() => onDecide("deny")}>Nega</Button>
        </div>
      )}
      {open && result && (
        <div className={styles.args} style={{ maxHeight: 280, overflow: "auto", color: tokens.colorNeutralForeground2 }}>
          {(() => {
            try {
              return JSON.stringify(JSON.parse(result.content), null, 2);
            } catch {
              return result.content;
            }
          })()}
        </div>
      )}
    </div>
  );
}
