import {
  Body1,
  Button,
  Caption1,
  Card,
  Field,
  Input,
  ProgressBar,
  Subtitle2,
  Title3,
  tokens,
  makeStyles,
} from "@fluentui/react-components";
import { ArrowDownloadRegular, DeleteRegular, PlayRegular, SearchRegular, StopRegular } from "@fluentui/react-icons";
import { useCallback, useEffect, useState } from "react";
import { api, formatBytes, type OllamaLibraryModel, type OllamaStatus } from "../api";
import { useStore } from "../store";

const useStyles = makeStyles({
  card: { display: "grid", gap: "12px", maxWidth: "900px", marginBottom: "16px" },
  row: { display: "flex", alignItems: "center", gap: "12px", padding: "6px 0", borderBottom: `1px solid ${tokens.colorNeutralStroke2}` },
  name: { flex: "1 1 260px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  meta: { flex: "0 0 220px", color: tokens.colorNeutralForeground3 },
  actions: { flex: "0 0 auto", display: "flex", gap: "8px" },
  search: { display: "flex", gap: "8px", alignItems: "flex-end" },
});

interface PullProgress {
  status: string;
  completed: number | null;
  total: number | null;
  error?: string;
}

export default function ModelsPage() {
  const styles = useStyles();
  const store = useStore();
  const [status, setStatus] = useState<OllamaStatus | null>(null);
  const [query, setQuery] = useState("");
  const [library, setLibrary] = useState<OllamaLibraryModel[]>([]);
  const [searching, setSearching] = useState(false);
  const [pulls, setPulls] = useState<Record<string, PullProgress>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.ollamaStatus());
    } catch {
      setStatus({ online: false, installed: [], running: [] });
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(
    () =>
      store.onOllamaEvent((e) => {
        setPulls((prev) => ({
          ...prev,
          [e.model]: { status: e.status, completed: e.completed, total: e.total, error: e.error },
        }));
        if (e.status === "download_completato" || e.status === "errore") refresh();
      }),
    [store, refresh],
  );

  const runningNames = new Set((status?.running ?? []).map((m) => m.name));
  // Miglioramento #5: library names carry no tag (llama3.2) while installed ones do
  // (llama3.2:latest): compare against the tagless form.
  const installedNames = new Set((status?.installed ?? []).map((m) => m.name.split(":")[0]));

  async function search() {
    setSearching(true);
    try {
      const r = await api.ollamaLibrary(query);
      setLibrary(r.models);
    } catch (e) {
      store.notify(`Ricerca libreria fallita: ${(e as Error).message}`, "error");
    } finally {
      setSearching(false);
    }
  }

  async function pull(model: string) {
    try {
      await api.ollamaPull(model);
      setPulls((prev) => ({ ...prev, [model]: { status: "download_avviato", completed: null, total: null } }));
    } catch (e) {
      store.notify((e as Error).message, "error");
    }
  }

  async function act(kind: "load" | "unload" | "delete", model: string) {
    setBusy(`${kind}:${model}`);
    try {
      if (kind === "load") await api.ollamaLoad(model, store.settings?.ollama_keep_alive_minutes ?? 30);
      else if (kind === "unload") await api.ollamaUnload(model);
      else if (window.confirm(`Eliminare definitivamente ${model} dal disco?`)) await api.ollamaDelete(model);
      await refresh();
    } catch (e) {
      store.notify((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  // Bug #2: a failed download must surface the error AND offer a retry; clearing the
  // progress entry restores the action buttons instead of spinning forever.
  async function retry(model: string) {
    setPulls((prev) => {
      const next = { ...prev };
      delete next[model];
      return next;
    });
    await pull(model);
  }

  const progressOf = (model: string) => {
    const p = pulls[model];
    if (!p || p.status === "download_completato") return null;
    const pct = p.total ? Math.min(100, Math.round(((p.completed ?? 0) / p.total) * 100)) : null;
    return { ...p, pct };
  };

  return (
    <>
      <Title3 as="h1">Modelli (Ollama)</Title3>
      <Body1 as="p" style={{ color: tokens.colorNeutralForeground3 }}>
        Scarica, carica e libera i modelli locali. Quando un Vault o l'agente richiedono un modello non presente, viene scaricato
        automaticamente (Impostazioni → Ollama).
      </Body1>

      {!status?.online && (
        <Card className={styles.card}>
          <Subtitle2>Ollama non raggiungibile</Subtitle2>
          <Body1>
            Avvia Ollama (oppure installalo da <code>ollama.com</code>) oppure verifica l'endpoint in Impostazioni. LM Studio resta
            disponibile come alternativa.
          </Body1>
        </Card>
      )}

      {status?.online && (
        <>
          <Card className={styles.card}>
            <Subtitle2>In memoria (RAM/VRAM)</Subtitle2>
            {status.running.length === 0 && <Caption1>Nessun modello caricato: memoria libera.</Caption1>}
            {status.running.map((m) => (
              <div key={m.name} className={styles.row}>
                <span className={styles.name}>{m.name}</span>
                <span className={styles.meta}>
                  VRAM {formatBytes(m.size_vram)} · totale {formatBytes(m.size)}
                </span>
                <span className={styles.actions}>
                  <Button size="small" icon={<StopRegular />} disabled={busy !== null} onClick={() => act("unload", m.name)}>
                    Libera
                  </Button>
                </span>
              </div>
            ))}
          </Card>

          <Card className={styles.card}>
            <Subtitle2>Installati su disco</Subtitle2>
            {status.installed.length === 0 && <Caption1>Nessun modello installato.</Caption1>}
            {status.installed.map((m) => {
              const running = runningNames.has(m.name);
              const prog = progressOf(m.name);
              return (
                <div key={m.name} className={styles.row}>
                  <span className={styles.name}>
                    {m.name}
                    {running && <Caption1> · in memoria</Caption1>}
                  </span>
                  <span className={styles.meta}>{formatBytes(m.size)} su disco</span>
                  <span className={styles.actions}>
                    {prog ? (
                      prog.error ? (
                        <>
                          <Caption1
                            style={{ color: tokens.colorPaletteRedForeground1, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}
                            title={prog.error}
                          >
                            Errore: {prog.error}
                          </Caption1>
                          <Button size="small" icon={<ArrowDownloadRegular />} disabled={busy !== null} onClick={() => retry(m.name)}>
                            Riprova
                          </Button>
                        </>
                      ) : (
                        <Caption1 style={{ minWidth: 140 }}>
                          {`${prog.status}${prog.pct !== null ? ` · ${prog.pct}%` : "…"}`}
                        </Caption1>
                      )
                    ) : (
                      <>
                        {!running && (
                          <Button size="small" icon={<PlayRegular />} disabled={busy !== null} onClick={() => act("load", m.name)}>
                            Carica
                          </Button>
                        )}
                        <Button size="small" icon={<DeleteRegular />} appearance="subtle" disabled={busy !== null} onClick={() => act("delete", m.name)}>
                          Elimina
                        </Button>
                      </>
                    )}
                  </span>
                </div>
              );
            })}
          </Card>
        </>
      )}

      <Card className={styles.card}>
        <Subtitle2>Libreria modelli (ollama.com)</Subtitle2>
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Attenzione: il testo cercato viene inviato a ollama.com (unica chiamata di rete del programma).
        </Caption1>
        <div className={styles.search}>
          <Field label="Cerca" style={{ flex: 1 }}>
            <Input
              value={query}
              placeholder="es. bge-m3, llama3.2, qwen2.5"
              onChange={(_, d) => setQuery(d.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
            />
          </Field>
          <Button appearance="primary" icon={<SearchRegular />} disabled={searching} onClick={search}>
            Cerca
          </Button>
        </div>
        {library.map((m) => {
          const prog = progressOf(m.name);
          const installed = installedNames.has(m.name.split(":")[0]);
          return (
            <div key={m.name} className={styles.row}>
              <span className={styles.name}>
                {m.name}
                {m.label && m.label !== m.name && <Caption1> · {m.label}</Caption1>}
              </span>
              <span className={styles.meta}>{installed ? "installato" : ""}</span>
              <span className={styles.actions}>
                {prog ? (
                  prog.error ? (
                    <span style={{ minWidth: 160, display: "inline-block" }}>
                      <Caption1 style={{ color: tokens.colorPaletteRedForeground1 }} title={prog.error}>
                        Errore: {prog.error}
                      </Caption1>{" "}
                      <Button size="small" icon={<ArrowDownloadRegular />} onClick={() => retry(m.name)}>
                        Riprova
                      </Button>
                    </span>
                  ) : (
                    <span style={{ minWidth: 160, display: "inline-block" }}>
                      <ProgressBar value={prog.pct !== null ? prog.pct / 100 : undefined} />
                      <Caption1>{`${prog.status}${prog.pct !== null ? ` · ${prog.pct}%` : "…"}`}</Caption1>
                    </span>
                  )
                ) : installed ? (
                  <Caption1>✓</Caption1>
                ) : (
                  <Button size="small" icon={<ArrowDownloadRegular />} onClick={() => pull(m.name)}>
                    Scarica
                  </Button>
                )}
              </span>
            </div>
          );
        })}
      </Card>
    </>
  );
}
