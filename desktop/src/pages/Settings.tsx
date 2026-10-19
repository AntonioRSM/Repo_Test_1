import {
  Body1,
  Button,
  Caption1,
  Card,
  Dropdown,
  Field,
  Input,
  makeStyles,
  Option,
  SpinButton,
  Subtitle2,
  Switch,
  Title3,
  tokens,
} from "@fluentui/react-components";
import { CheckmarkRegular } from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { api, modelLabel, type AppSettings, type ModelRef, type OcrSettings } from "../api";
import { McpServers } from "../components/McpServers";
import { useModels, useStore } from "../store";

const useStyles = makeStyles({
  card: { display: "grid", gap: "14px", maxWidth: "820px", marginBottom: "16px" },
  row: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" },
});

const key = (r: ModelRef | null | undefined) => (r ? `${r.provider}::${r.model}` : "");
const parse = (k: string): ModelRef | null => {
  if (!k) return null;
  const [provider, ...rest] = k.split("::");
  return { provider: provider as ModelRef["provider"], model: rest.join("::") };
};

function ModelSelect({ label, hint, kind, value, onChange, allowNone }: {
  label: string; hint?: string; kind: "embedding" | "llm" | "vision"; value: ModelRef | null; onChange: (m: ModelRef | null) => void; allowNone?: boolean;
}) {
  const models = useModels(kind);
  return (
    <Field label={label} hint={hint}>
      <Dropdown value={value ? modelLabel(value) : "Nessuno"} selectedOptions={[key(value)]} onOptionSelect={(_, d) => onChange(parse(d.optionValue ?? ""))}>
        {allowNone && <Option value="">Nessuno</Option>}
        {models.map((m) => (
          <Option key={key(m)} value={key(m)} text={modelLabel(m)}>
            {modelLabel(m)}{m.loaded ? " · caricato" : ""}
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
}

export default function SettingsPage() {
  const styles = useStyles();
  const store = useStore();
  const [draft, setDraft] = useState<AppSettings | null>(store.settings);
  const [test, setTest] = useState<string | null>(null);

  useEffect(() => setDraft(store.settings), [store.settings]);
  if (!draft) return null;
  const set = (patch: Partial<AppSettings>) => setDraft({ ...draft, ...patch });
  const setOcr = (patch: Partial<OcrSettings>) => set({ ocr: { ...draft.ocr, ...patch } });

  async function save() {
    const saved = await api.updateSettings(draft!);
    store.setSettings(saved);
    store.notify("Impostazioni salvate", "success");
    store.refreshProviders();
  }

  async function testEmbedding() {
    if (!draft?.default_embedding) return;
    setTest("Test in corso…");
    try {
      const r = await api.testEmbedding(draft.default_embedding);
      setTest(`OK · ${r.dimension} dimensioni`);
    } catch (e) {
      setTest(`Errore: ${(e as Error).message}`);
    }
  }

  return (
    <>
      <Title3 as="h1">Impostazioni</Title3>
      <Body1 as="p" style={{ color: tokens.colorNeutralForeground3 }}>Server locali, Model Router, OCR e prestazioni.</Body1>

      <Card className={styles.card}>
        <Subtitle2>Server locali (auto-discovery)</Subtitle2>
        <div className={styles.row}>
          <Field label="LM Studio" hint="Endpoint compatibile OpenAI">
            <Input value={draft.endpoints.lmstudio} onChange={(_, d) => set({ endpoints: { ...draft.endpoints, lmstudio: d.value } })} />
          </Field>
          <Field label="Ollama">
            <Input value={draft.endpoints.ollama} onChange={(_, d) => set({ endpoints: { ...draft.endpoints, ollama: d.value } })} />
          </Field>
        </div>
      </Card>

      <Card className={styles.card}>
        <Subtitle2>Model Router</Subtitle2>
        <div className={styles.row}>
          <ModelSelect
            label="Embedding predefinito per i nuovi Vault"
            hint="es. bge-m3 (multilingue), nomic-embed-text"
            kind="embedding"
            value={draft.default_embedding}
            onChange={(m) => set({ default_embedding: m })}
          />
          <Field label="Verifica">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Button onClick={testEmbedding} disabled={!draft.default_embedding}>Prova embedding</Button>
              <Caption1>{test}</Caption1>
            </div>
          </Field>
        </div>
        <ModelSelect
          label="LLM per riassunti, chunking contestuale, re-ranking e risposte RAG"
          hint="es. Qwen 2.5, Llama 3.3, DeepSeek-R1-Distill (i blocchi <think> vengono rimossi)"
          kind="llm"
          value={draft.llm}
          onChange={(m) => set({ llm: m })}
          allowNone
        />
      </Card>

      <Card className={styles.card}>
        <Subtitle2>OCR predefinito</Subtitle2>
        <div className={styles.row}>
          <Field label="Motore">
            <Dropdown
              value={{ rapidocr: "RapidOCR (ONNX, locale)", tesseract: "Tesseract 5", vision: "Vision LLM", none: "Disattivato" }[draft.ocr.engine]}
              selectedOptions={[draft.ocr.engine]}
              onOptionSelect={(_, d) => setOcr({ engine: d.optionValue as OcrSettings["engine"] })}
            >
              <Option value="rapidocr">RapidOCR (ONNX, locale)</Option>
              <Option value="tesseract">Tesseract 5</Option>
              <Option value="vision">Vision LLM</Option>
              <Option value="none">Disattivato</Option>
            </Dropdown>
          </Field>
          {draft.ocr.engine === "vision" && (
            <ModelSelect label="Modello vision" hint="es. llava, qwen2-vl, gemma" kind="vision" value={draft.ocr.vision} onChange={(m) => setOcr({ vision: m })} />
          )}
        </div>
        <div className={styles.row}>
          <Field label="Soglia pagina scansionata" hint="Pagine PDF con meno caratteri estraibili passano all'OCR">
            <SpinButton value={draft.ocr.min_text_chars_per_page} min={0} max={2000} step={10}
              onChange={(_, d) => setOcr({ min_text_chars_per_page: d.value ?? (Number(d.displayValue) || 40) })} />
          </Field>
          <Field label="Lingue OCR (Tesseract)" hint="Codici separati da virgola, es. it,en,de">
            <Input value={draft.ocr.languages.join(",")} onChange={(_, d) => setOcr({ languages: d.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
          </Field>
        </div>
      </Card>

      <Card className={styles.card}>
        <Subtitle2>Prestazioni</Subtitle2>
        <div className={styles.row}>
          <Field label="File elaborati in parallelo" hint="Riduci se RAM o VRAM sono sature durante OCR ed embedding">
            <SpinButton value={draft.ingest_workers} min={1} max={16} onChange={(_, d) => set({ ingest_workers: d.value ?? (Number(d.displayValue) || 2) })} />
          </Field>
          <Field label="Batch embedding" hint="Testi per richiesta al server">
            <SpinButton value={draft.embed_batch_size} min={1} max={256} onChange={(_, d) => set({ embed_batch_size: d.value ?? (Number(d.displayValue) || 32) })} />
          </Field>
        </div>
      </Card>

      <Card className={styles.card}>
        <Subtitle2>Ollama</Subtitle2>
        <div className={styles.row}>
          <Field
            label="Scaricamento automatico"
            hint="Quando un Vault o l'agente richiedono un modello Ollama non presente, viene scaricato da solo (con barra di avanzamento nella pagina Modelli)"
          >
            <Switch checked={draft.ollama_auto_pull} onChange={(_, d) => set({ ollama_auto_pull: d.checked })} label={draft.ollama_auto_pull ? "Attivo" : "Disattivato"} />
          </Field>
          <Field label="Tempo di residenza in memoria" hint="Minuti dopo cui Ollama libera RAM/VRAM di un modello non usato (1-240)">
            <SpinButton value={draft.ollama_keep_alive_minutes} min={1} max={240} onChange={(_, d) => set({ ollama_keep_alive_minutes: d.value ?? (Number(d.displayValue) || 30) })} />
          </Field>
        </div>
        <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
          La pagina Modelli permette di cercare nella libreria, scaricare, caricare in memoria e liberare RAM/VRAM manualmente.
        </Body1>
      </Card>

      <Card className={styles.card}>
        <Subtitle2>Agente</Subtitle2>
        <div className={styles.row}>
          <Field label="Passi massimi per richiesta" hint="Ogni passo è una chiamata al modello; poi l'agente deve rispondere">
            <SpinButton value={draft.agent_max_steps} min={1} max={40} onChange={(_, d) => set({ agent_max_steps: d.value ?? (Number(d.displayValue) || 10) })} />
          </Field>
          <Field label="Token massimi per risposta">
            <SpinButton value={draft.agent_max_tokens} min={256} max={16384} step={256} onChange={(_, d) => set({ agent_max_tokens: d.value ?? (Number(d.displayValue) || 2048) })} />
          </Field>
        </div>
        <Switch
          checked={draft.agent_reasoning}
          onChange={(_, d) => set({ agent_reasoning: d.checked })}
          label="Lascia ragionare i modelli di ragionamento (piani migliori, ma più volte più lento su CPU)"
        />
      </Card>

      <Button appearance="primary" icon={<CheckmarkRegular />} onClick={save} style={{ marginBottom: 24 }}>Salva impostazioni</Button>

      {/* MCP servers are saved individually, not with the button above. */}
      <McpServers />
    </>
  );
}
