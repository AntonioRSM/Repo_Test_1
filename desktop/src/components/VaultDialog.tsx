import {
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  makeStyles,
  MessageBar,
  MessageBarBody,
  Option,
  Radio,
  RadioGroup,
  SpinButton,
  Switch,
  Tag,
  TagGroup,
  Textarea,
} from "@fluentui/react-components";
import { FolderAddRegular } from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { api, isDesktop, modelLabel, type ModelRef, type OcrSettings, type Vault, type VaultInput } from "../api";
import { useModels, useStore } from "../store";

const useStyles = makeStyles({
  form: { display: "grid", gap: "14px" },
  row: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" },
  folders: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" },
});

const key = (r: ModelRef | null | undefined) => (r ? `${r.provider}::${r.model}` : "");
const parse = (k: string): ModelRef => {
  const [provider, ...rest] = k.split("::");
  return { provider: provider as ModelRef["provider"], model: rest.join("::") };
};

export function VaultDialog({ open, vault, onClose }: { open: boolean; vault?: Vault; onClose: (saved?: Vault) => void }) {
  const styles = useStyles();
  const { settings, notify } = useStore();
  const embeddingModels = useModels("embedding");
  const visionModels = useModels("vision");
  const llmModels = useModels("llm");
  const [form, setForm] = useState<VaultInput | null>(null);
  const [manualFolder, setManualFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(
      vault
        ? { ...vault }
        : {
            name: "",
            description: "",
            sources: [],
            embedding: settings?.default_embedding ?? embeddingModels[0] ?? { provider: "lmstudio", model: "" },
            chunking: { strategy: "recursive", chunk_size: 1000, chunk_overlap: 150, breakpoint_percentile: 90, min_chunk_size: 200 },
            ocr: null,
            parser: "builtin",
            contextual_summary: false,
            watch: true,
            metric: "cosine",
          },
    );
    // Only reinitialise when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, vault]);

  if (!form) return null;
  const set = (patch: Partial<VaultInput>) => setForm({ ...form, ...patch });
  const ocr: OcrSettings | null = form.ocr;
  const embeddingChanged = vault && key(vault.embedding) !== key(form.embedding);

  async function addFolders() {
    if (isDesktop) {
      const picked = await window.wsos!.pickFolders();
      set({ sources: [...new Set([...form!.sources, ...picked])] });
    } else if (manualFolder.trim()) {
      set({ sources: [...new Set([...form!.sources, manualFolder.trim()])] });
      setManualFolder("");
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const saved = vault ? await api.updateVault(vault.id, form!) : await api.createVault(form!);
      notify(vault ? "Vault aggiornato" : `Vault "${saved.name}" creato: indicizzazione avviata`, "success");
      onClose(saved);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface style={{ maxWidth: 720 }}>
        <DialogBody>
          <DialogTitle>{vault ? `Modifica ${vault.name}` : "Nuovo Vault"}</DialogTitle>
          <DialogContent className={styles.form}>
            <Field label="Nome" required>
              <Input value={form.name} onChange={(_, d) => set({ name: d.value })} placeholder="es. Contratti fornitori" />
            </Field>
            <Field label="Descrizione">
              <Textarea value={form.description} onChange={(_, d) => set({ description: d.value })} resize="vertical" />
            </Field>

            <Field label="Cartelle sorgente (RAW)" hint="Sorvegliate in background: le modifiche vengono indicizzate automaticamente.">
              <div className={styles.folders}>
                <TagGroup onDismiss={(_, d) => set({ sources: form.sources.filter((s) => s !== d.value) })}>
                  {form.sources.map((s) => (
                    <Tag key={s} value={s} dismissible title={s}>
                      {s}
                    </Tag>
                  ))}
                </TagGroup>
                {!isDesktop && (
                  <Input value={manualFolder} onChange={(_, d) => setManualFolder(d.value)} placeholder="C:\\percorso\\cartella" />
                )}
                <Button icon={<FolderAddRegular />} onClick={addFolders}>
                  {isDesktop ? "Aggiungi cartelle…" : "Aggiungi"}
                </Button>
              </div>
            </Field>

            <div className={styles.row}>
              <Field
                label="Modello di embedding"
                validationState={embeddingChanged ? "warning" : "none"}
                validationMessage={embeddingChanged ? "Cambiare modello ricostruisce l'intero Vault" : undefined}
              >
                <Dropdown
                  value={modelLabel(form.embedding)}
                  selectedOptions={[key(form.embedding)]}
                  onOptionSelect={(_, d) => d.optionValue && set({ embedding: parse(d.optionValue) })}
                  placeholder="Nessun modello di embedding trovato"
                >
                  {embeddingModels.map((m) => (
                    <Option key={key(m)} value={key(m)} text={modelLabel(m)}>
                      {modelLabel(m)}
                    </Option>
                  ))}
                </Dropdown>
              </Field>
              <Field label="Metrica di similarità">
                <Dropdown
                  value={{ cosine: "Cosine similarity", dot: "Dot product", l2: "Distanza euclidea" }[form.metric]}
                  selectedOptions={[form.metric]}
                  onOptionSelect={(_, d) => set({ metric: d.optionValue as VaultInput["metric"] })}
                >
                  <Option value="cosine">Cosine similarity</Option>
                  <Option value="dot">Dot product</Option>
                  <Option value="l2">Distanza euclidea</Option>
                </Dropdown>
              </Field>
            </div>

            <Field label="Chunking">
              <RadioGroup
                layout="horizontal"
                value={form.chunking.strategy}
                onChange={(_, d) => set({ chunking: { ...form.chunking, strategy: d.value as "recursive" } })}
              >
                <Radio value="recursive" label="Ricorsivo (dimensione + overlap)" />
                <Radio value="semantic" label="Semantico (per significato, più lento)" />
              </RadioGroup>
            </Field>
            <div className={styles.row}>
              <Field label="Dimensione chunk (caratteri)">
                <SpinButton
                  value={form.chunking.chunk_size}
                  min={100}
                  max={8000}
                  step={100}
                  onChange={(_, d) => set({ chunking: { ...form.chunking, chunk_size: d.value ?? Number(d.displayValue) ?? 1000 } })}
                />
              </Field>
              <Field label="Overlap (caratteri)">
                <SpinButton
                  value={form.chunking.chunk_overlap}
                  min={0}
                  max={2000}
                  step={25}
                  onChange={(_, d) => set({ chunking: { ...form.chunking, chunk_overlap: d.value ?? Number(d.displayValue) ?? 0 } })}
                />
              </Field>
            </div>

            <div className={styles.row}>
              <Field label="Motore OCR">
                <Dropdown
                  value={ocr ? { rapidocr: "RapidOCR (ONNX)", tesseract: "Tesseract 5", vision: "Vision LLM", none: "Nessuno" }[ocr.engine] : "Predefinito (Impostazioni)"}
                  selectedOptions={[ocr?.engine ?? "default"]}
                  onOptionSelect={(_, d) =>
                    set({
                      ocr:
                        d.optionValue === "default"
                          ? null
                          : { ...(settings?.ocr ?? { min_text_chars_per_page: 40, languages: ["it", "en"], vision: null }), engine: d.optionValue as OcrSettings["engine"] },
                    })
                  }
                >
                  <Option value="default">Predefinito (Impostazioni)</Option>
                  <Option value="rapidocr">RapidOCR (ONNX)</Option>
                  <Option value="tesseract">Tesseract 5</Option>
                  <Option value="vision">Vision LLM</Option>
                  <Option value="none">Nessuno</Option>
                </Dropdown>
              </Field>
              {ocr?.engine === "vision" && (
                <Field label="Modello vision">
                  <Dropdown
                    value={modelLabel(ocr.vision)}
                    selectedOptions={[key(ocr.vision)]}
                    onOptionSelect={(_, d) => d.optionValue && set({ ocr: { ...ocr, vision: parse(d.optionValue) } })}
                    placeholder="Nessun modello vision trovato"
                  >
                    {visionModels.map((m) => (
                      <Option key={key(m)} value={key(m)} text={modelLabel(m)}>
                        {modelLabel(m)}
                      </Option>
                    ))}
                  </Dropdown>
                </Field>
              )}
            </div>

            <Switch
              checked={form.contextual_summary}
              onChange={(_, d) => set({ contextual_summary: d.checked })}
              label="Chunking contestuale: un LLM riassume ogni documento e il riassunto arricchisce ogni chunk"
            />
            {form.contextual_summary && !settings?.llm && (
              <Caption1>Seleziona un LLM in Impostazioni, altrimenti questa opzione viene ignorata.</Caption1>
            )}
            {form.contextual_summary && settings?.llm && (
              <ContestoLlmWarning llm={settings.llm} llmModels={llmModels} />
            )}
            <Switch checked={form.watch} onChange={(_, d) => set({ watch: d.checked })} label="Live-watching delle cartelle" />
            <Switch
              checked={form.parser === "docling"}
              onChange={(_, d) => set({ parser: d.checked ? "docling" : "builtin" })}
              label="Parser Docling per PDF/Office (layout avanzato, richiede l'estensione docling)"
            />

            {error && (
              <MessageBar intent="error">
                <MessageBarBody>{error}</MessageBarBody>
              </MessageBar>
            )}
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={() => onClose()}>
              Annulla
            </Button>
            <Button appearance="primary" disabled={busy || !form.name.trim() || !form.embedding.model} onClick={save}>
              {vault ? "Salva" : "Crea e indicizza"}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// Miglioramento #23: sotto gli 8.192 token di contesto i documenti lunghi rischiano di
// superare la finestra del modello durante il riassunto (Bug #32). Il contesto letto da
// Ollama/LM Studio arriva in ModelInfo.context_length; se sconosciuto non si avvisa.
function ContestoLlmWarning({
  llm,
  llmModels,
}: {
  llm: ModelRef;
  llmModels: { provider: ModelRef["provider"]; model: string; loaded: boolean | null; context_length: number | null }[];
}) {
  const found = llmModels.find((m) => m.provider === llm.provider && m.model === llm.model);
  const ctx = found?.context_length;
  if (!ctx) return null;
  if (ctx < 8192) {
    return (
      <Caption1>
        Il modello {llm.model} ha un contesto di circa {ctx.toLocaleString("it-IT")} token: i documenti lunghi potrebbero
        restare senza riassunto contestuale. Consigliato un modello con almeno 8.192 token (es. workspace-agent).
      </Caption1>
    );
  }
  return (
    <Caption1>
      Contesto del modello {llm.model}: circa {ctx.toLocaleString("it-IT")} token, sufficiente per il riassunto contestuale.
    </Caption1>
  );
}
