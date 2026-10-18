import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  Dropdown,
  Field,
  Input,
  makeStyles,
  MessageBar,
  MessageBarBody,
  Option,
  SpinButton,
  Spinner,
  Switch,
  Text,
  Title3,
  tokens,
} from "@fluentui/react-components";
import { ChatRegular, OpenRegular, SearchRegular } from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { api, isDesktop, type Metric, type SearchHit } from "../api";
import { VaultPicker } from "../components/VaultPicker";
import { useStore } from "../store";

const useStyles = makeStyles({
  controls: { display: "flex", gap: "12px", alignItems: "end", flexWrap: "wrap", marginBottom: "16px" },
  hit: { display: "grid", gap: "6px" },
  scores: { display: "flex", gap: "6px", flexWrap: "wrap" },
  text: { whiteSpace: "pre-wrap", fontSize: "13px", padding: "8px 10px", borderRadius: tokens.borderRadiusMedium, background: tokens.colorNeutralBackground3 },
  answer: { whiteSpace: "pre-wrap", lineHeight: 1.5 },
  bar: { height: "6px", borderRadius: "3px", background: tokens.colorBrandBackground },
});

const METRIC_LABEL: Record<Metric, string> = { cosine: "Cosine similarity", dot: "Dot product", l2: "Distanza euclidea" };

export default function SearchPage({ initialId }: { initialId?: string }) {
  const styles = useStyles();
  const { vaults, settings } = useStore();
  const [vaultId, setVaultId] = useState<string | undefined>(initialId ?? vaults[0]?.id);
  const vault = vaults.find((v) => v.id === vaultId);
  const [query, setQuery] = useState("");
  const [k, setK] = useState(8);
  const [metric, setMetric] = useState<Metric>("cosine");
  const [rerank, setRerank] = useState(false);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [busy, setBusy] = useState<"search" | "ask" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rerankError, setRerankError] = useState<string | null>(null);

  useEffect(() => {
    if (vault) setMetric(vault.metric);
  }, [vault?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(mode: "search" | "ask") {
    if (!vaultId || !query.trim()) return;
    setBusy(mode);
    setError(null);
    setRerankError(null);
    setAnswer(null);
    try {
      if (mode === "search") {
        const res = await api.search(vaultId, { query, k, metric, rerank });
        setHits(res.results);
        setRerankError(res.rerank_error);
      } else {
        const res = await api.ask(vaultId, { query, k, rerank });
        setAnswer(res.answer);
        setHits(res.sources);
        setRerankError(res.rerank_error);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const maxCos = Math.max(0.0001, ...(hits ?? []).map((h) => h.scores.cosine));

  return (
    <>
      <Title3 as="h1">Search &amp; Retrieval</Title3>
      <Body1 as="p" style={{ color: tokens.colorNeutralForeground3 }}>
        Verifica la pertinenza dei chunk restituiti per una domanda, con le tre metriche di similarità a confronto.
      </Body1>
      <div className={styles.controls}>
        <VaultPicker value={vaultId} onChange={setVaultId} />
        <Field label="Domanda" style={{ flex: 1, minWidth: 320 }}>
          <Input
            value={query}
            onChange={(_, d) => setQuery(d.value)}
            onKeyDown={(e) => e.key === "Enter" && run("search")}
            placeholder="es. Qual è la penale per ritardata consegna?"
            contentBefore={<SearchRegular />}
          />
        </Field>
        <Field label="Top-k">
          <SpinButton value={k} min={1} max={50} onChange={(_, d) => setK(d.value ?? (Number(d.displayValue) || 8))} style={{ width: 90 }} />
        </Field>
        <Field label="Metrica di ordinamento">
          <Dropdown value={METRIC_LABEL[metric]} selectedOptions={[metric]} onOptionSelect={(_, d) => setMetric(d.optionValue as Metric)}>
            {(Object.keys(METRIC_LABEL) as Metric[]).map((m) => (
              <Option key={m} value={m}>{METRIC_LABEL[m]}</Option>
            ))}
          </Dropdown>
        </Field>
        <Switch checked={rerank} disabled={!settings?.llm} onChange={(_, d) => setRerank(d.checked)} label="Re-ranking LLM" />
        <Button appearance="primary" icon={<SearchRegular />} disabled={!vaultId || !query.trim() || !!busy} onClick={() => run("search")}>
          Cerca
        </Button>
        <Button icon={<ChatRegular />} disabled={!vaultId || !query.trim() || !!busy || !settings?.llm} onClick={() => run("ask")}>
          Chiedi (RAG)
        </Button>
      </div>
      {!settings?.llm && <Caption1>Configura un LLM in Impostazioni per abilitare re-ranking e risposte RAG.</Caption1>}
      {busy && <Spinner label={busy === "ask" ? "Recupero e generazione della risposta…" : "Ricerca…"} />}
      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      )}

      {rerankError && (
        <MessageBar intent="warning" style={{ marginBottom: 12 }}>
          <MessageBarBody>Re-ranking non riuscito, risultati in ordine di similarità: {rerankError}</MessageBarBody>
        </MessageBar>
      )}
      {answer && (
        <Card style={{ marginBottom: 16 }}>
          <Text weight="semibold">Risposta</Text>
          <div className={styles.answer}>{answer}</div>
        </Card>
      )}

      {hits && (
        <div style={{ display: "grid", gap: 12 }}>
          {hits.length === 0 && <Caption1>Nessun risultato.</Caption1>}
          {hits.map((h, i) => (
            <Card key={h.id} className={styles.hit}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                <Text weight="semibold">
                  [{i + 1}] {h.file_name}
                  {h.page_start ? ` · p. ${h.page_start}` : ""}
                </Text>
                {isDesktop && <Button size="small" appearance="subtle" icon={<OpenRegular />} onClick={() => window.wsos!.openPath(h.file_path)}>Apri</Button>}
              </div>
              {h.heading && <Caption1>{h.heading}</Caption1>}
              <div className={styles.bar} style={{ width: `${Math.max(4, (h.scores.cosine / maxCos) * 100)}%` }} />
              <div className={styles.scores}>
                <Badge appearance={metric === "cosine" ? "filled" : "tint"}>cosine {h.scores.cosine.toFixed(4)}</Badge>
                <Badge appearance={metric === "dot" ? "filled" : "tint"}>dot {h.scores.dot.toFixed(4)}</Badge>
                <Badge appearance={metric === "l2" ? "filled" : "tint"}>euclidea {h.scores.euclidean.toFixed(4)}</Badge>
                {h.rerank_score != null && <Badge color="important">rerank {h.rerank_score}/10</Badge>}
                {h.language && <Badge appearance="outline">{h.language}</Badge>}
                {h.ocr && <Badge appearance="outline">OCR</Badge>}
              </div>
              <div className={styles.text}>{h.text}</div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
