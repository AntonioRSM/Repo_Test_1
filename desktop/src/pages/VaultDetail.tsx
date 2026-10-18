import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  Drawer,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  Input,
  makeStyles,
  Tab,
  TabList,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  Title3,
  tokens,
  Tooltip,
} from "@fluentui/react-components";
import { ArrowLeftRegular, ArrowSyncRegular, DismissRegular, FolderOpenRegular, OpenRegular, SearchRegular } from "@fluentui/react-icons";
import { useCallback, useEffect, useState } from "react";
import type { Route } from "../App";
import { api, formatBytes, isDesktop, type ChunkRow, type FileRecord } from "../api";
import { JobProgress } from "../components/JobProgress";
import { useActiveJobs, useStore } from "../store";

const useStyles = makeStyles({
  header: { display: "flex", alignItems: "center", gap: "12px", marginBottom: "12px" },
  toolbar: { display: "flex", gap: "12px", alignItems: "center", margin: "12px 0" },
  path: { maxWidth: "460px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" },
  chunk: { padding: "10px 12px", borderRadius: tokens.borderRadiusMedium, background: tokens.colorNeutralBackground3, whiteSpace: "pre-wrap", fontSize: "13px" },
  meta: { display: "grid", gridTemplateColumns: "120px 1fr", gap: "4px 12px", fontSize: "13px", marginBottom: "16px" },
});

const STATUS_COLOR = { indexed: "success", error: "danger", skipped: "warning", pending: "informative" } as const;
const STATUS_LABEL = { indexed: "Indicizzato", error: "Errore", skipped: "Saltato", pending: "In attesa" } as const;

export default function VaultDetail({ id, go }: { id: string; go: (r: Route) => void }) {
  const styles = useStyles();
  const { vaults } = useStore();
  const vault = vaults.find((v) => v.id === id);
  const jobs = useActiveJobs(id);
  const [status, setStatus] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [selected, setSelected] = useState<FileRecord | null>(null);

  const load = useCallback(async () => {
    setFiles(await api.files(id, { status: status === "all" ? undefined : status, q: query || undefined, limit: 1000 }));
  }, [id, status, query]);

  // Reload when the vault's stats change (files processed by background jobs).
  useEffect(() => {
    load();
  }, [load, vault?.stats.files, vault?.stats.vectors]);

  if (!vault) return <Body1>Vault non trovato.</Body1>;

  return (
    <>
      <div className={styles.header}>
        <Button appearance="subtle" icon={<ArrowLeftRegular />} onClick={() => go({ page: "vaults" })} aria-label="Indietro" />
        <Title3 as="h1">{vault.name}</Title3>
        <Badge appearance="tint">{vault.stats.files} file</Badge>
        <Badge appearance="tint">{vault.stats.vectors} chunk</Badge>
        <div style={{ flex: 1 }} />
        <Button icon={<SearchRegular />} onClick={() => go({ page: "search", id })}>Testa ricerca</Button>
        <Button icon={<ArrowSyncRegular />} appearance="primary" disabled={vault.busy} onClick={() => api.sync(id)}>Sincronizza</Button>
      </div>
      {jobs.map((j) => (
        <Card key={j.id} style={{ marginBottom: 12 }}>
          <JobProgress job={j} />
        </Card>
      ))}

      <TabList selectedValue={status} onTabSelect={(_, d) => setStatus(String(d.value))}>
        <Tab value="all">Tutti</Tab>
        <Tab value="indexed">Indicizzati ({vault.stats.by_status.indexed ?? 0})</Tab>
        <Tab value="error">Errori ({vault.stats.by_status.error ?? 0})</Tab>
        <Tab value="skipped">Saltati ({vault.stats.by_status.skipped ?? 0})</Tab>
      </TabList>
      <div className={styles.toolbar}>
        <Input contentBefore={<SearchRegular />} placeholder="Filtra per percorso…" value={query} onChange={(_, d) => setQuery(d.value)} style={{ width: 360 }} />
        <Caption1>{files.length} risultati</Caption1>
      </div>

      <Table size="small" aria-label="File del Vault">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>File</TableHeaderCell>
            <TableHeaderCell style={{ width: 110 }}>Stato</TableHeaderCell>
            <TableHeaderCell style={{ width: 70 }}>Chunk</TableHeaderCell>
            <TableHeaderCell style={{ width: 90 }}>Dimensione</TableHeaderCell>
            <TableHeaderCell style={{ width: 70 }}>Lingua</TableHeaderCell>
            <TableHeaderCell style={{ width: 80 }}>OCR</TableHeaderCell>
            <TableHeaderCell>Note</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {files.map((f) => (
            <TableRow key={f.path} onClick={() => setSelected(f)} style={{ cursor: "pointer" }}>
              <TableCell>
                <Tooltip content={f.path} relationship="description">
                  <span className={styles.path}>{f.path.split(/[\\/]/).pop()}</span>
                </Tooltip>
              </TableCell>
              <TableCell>
                <Badge appearance="tint" color={STATUS_COLOR[f.status]}>{STATUS_LABEL[f.status]}</Badge>
              </TableCell>
              <TableCell>{f.chunks}</TableCell>
              <TableCell>{formatBytes(f.size)}</TableCell>
              <TableCell>{f.language ?? "—"}</TableCell>
              <TableCell>{f.ocr_pages ? `${f.ocr_pages} pag.` : "—"}</TableCell>
              <TableCell>
                <Caption1 truncate wrap={false} title={f.error ?? ""} style={{ color: f.status === "error" ? tokens.colorPaletteRedForeground1 : undefined }}>
                  {f.error ?? ""}
                </Caption1>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <FileDrawer vaultId={id} file={selected} onClose={() => setSelected(null)} onRemoved={() => { setSelected(null); load(); }} />
    </>
  );
}

function FileDrawer({ vaultId, file, onClose, onRemoved }: { vaultId: string; file: FileRecord | null; onClose: () => void; onRemoved: () => void }) {
  const styles = useStyles();
  const [chunks, setChunks] = useState<ChunkRow[]>([]);

  useEffect(() => {
    if (file) api.chunks(vaultId, { file: file.path, limit: 500 }).then((r) => setChunks(r.items));
    else setChunks([]);
  }, [vaultId, file]);

  return (
    <Drawer type="overlay" position="end" size="large" open={!!file} onOpenChange={(_, d) => !d.open && onClose()}>
      <DrawerHeader>
        <DrawerHeaderTitle action={<Button appearance="subtle" icon={<DismissRegular />} onClick={onClose} aria-label="Chiudi" />}>
          {file?.path.split(/[\\/]/).pop()}
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody>
        {file && (
          <>
            <div className={styles.meta}>
              <Caption1>Percorso</Caption1><Text size={200} style={{ wordBreak: "break-all" }}>{file.path}</Text>
              <Caption1>SHA-256</Caption1><Text size={200} font="monospace" style={{ wordBreak: "break-all" }}>{file.sha256}</Text>
              <Caption1>Titolo</Caption1><Text size={200}>{file.title ?? "—"}</Text>
              <Caption1>Autore</Caption1><Text size={200}>{file.author ?? "—"}</Text>
              <Caption1>Creato</Caption1><Text size={200}>{file.created ? new Date(file.created).toLocaleString() : "—"}</Text>
              <Caption1>Modificato</Caption1><Text size={200}>{file.modified ? new Date(file.modified).toLocaleString() : "—"}</Text>
              <Caption1>Pagine</Caption1><Text size={200}>{file.pages ?? "—"}{file.ocr_pages ? ` (${file.ocr_pages} via OCR: ${file.ocr_engine})` : ""}</Text>
              <Caption1>Indicizzato</Caption1><Text size={200}>{new Date(file.updated_at * 1000).toLocaleString()}</Text>
              {file.error && (<><Caption1>Note</Caption1><Text size={200}>{file.error}</Text></>)}
            </div>
            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              {isDesktop && <Button icon={<OpenRegular />} onClick={() => window.wsos!.openPath(file.path)}>Apri</Button>}
              {isDesktop && <Button icon={<FolderOpenRegular />} onClick={() => window.wsos!.showInFolder(file.path)}>Mostra nella cartella</Button>}
              <Button onClick={() => api.ingest(vaultId, [file.path])}>Reindicizza</Button>
              <Button onClick={async () => { await api.removeFile(vaultId, file.path); onRemoved(); }}>Rimuovi dall'indice</Button>
            </div>
            <Text weight="semibold">{chunks.length} chunk</Text>
            <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
              {chunks.map((c) => (
                <div key={c.id}>
                  <Caption1>
                    #{c.chunk_index}
                    {c.heading && ` · ${c.heading}`}
                    {c.page_start && ` · p. ${c.page_start}${c.page_end && c.page_end !== c.page_start ? `–${c.page_end}` : ""}`}
                    {` · ${c.text.length} caratteri`}
                  </Caption1>
                  <div className={styles.chunk}>{c.text}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </DrawerBody>
    </Drawer>
  );
}
