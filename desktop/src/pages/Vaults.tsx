import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  CardFooter,
  CardHeader,
  makeStyles,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Switch,
  Text,
  Title3,
  tokens,
} from "@fluentui/react-components";
import {
  AddRegular,
  ArrowSyncRegular,
  DatabaseRegular,
  DeleteRegular,
  EditRegular,
  MoreHorizontalRegular,
  SearchRegular,
} from "@fluentui/react-icons";
import { useState, type DragEvent } from "react";
import type { Route } from "../App";
import { api, formatBytes, isDesktop, modelLabel, type Vault } from "../api";
import { JobProgress } from "../components/JobProgress";
import { VaultDialog } from "../components/VaultDialog";
import { useActiveJobs, useStore } from "../store";

const useStyles = makeStyles({
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))", gap: "16px" },
  stats: { display: "flex", gap: "16px", flexWrap: "wrap" },
  stat: { display: "flex", flexDirection: "column" },
  num: { fontSize: tokens.fontSizeBase500, fontWeight: tokens.fontWeightSemibold },
  drop: { outline: `2px dashed ${tokens.colorBrandStroke1}`, outlineOffset: "-2px" },
  empty: { display: "grid", placeItems: "center", gap: "12px", padding: "64px", textAlign: "center" },
});

export default function Vaults({ go }: { go: (r: Route) => void }) {
  const styles = useStyles();
  const { vaults, refreshVaults } = useStore();
  const [dialog, setDialog] = useState<{ open: boolean; vault?: Vault }>({ open: false });

  return (
    <>
      <div className={styles.header}>
        <div>
          <Title3 as="h1">Vault</Title3>
          <Body1 as="p" style={{ color: tokens.colorNeutralForeground3, margin: "4px 0 0" }}>
            Archivi vettoriali separati per argomento, progetto o reparto. Trascina file o cartelle su un Vault per indicizzarli.
          </Body1>
        </div>
        <Button appearance="primary" icon={<AddRegular />} onClick={() => setDialog({ open: true })}>
          Nuovo Vault
        </Button>
      </div>

      {vaults.length === 0 ? (
        <Card className={styles.empty}>
          <DatabaseRegular fontSize={48} />
          <Text size={500} weight="semibold">Nessun Vault</Text>
          <Body1>Crea un Vault, scegli le cartelle da sorvegliare e il modello di embedding: al resto pensa RAG Vault Studio.</Body1>
          <Button appearance="primary" icon={<AddRegular />} onClick={() => setDialog({ open: true })}>
            Crea il primo Vault
          </Button>
        </Card>
      ) : (
        <div className={styles.grid}>
          {vaults.map((v) => (
            <VaultCard key={v.id} vault={v} go={go} onEdit={() => setDialog({ open: true, vault: v })} />
          ))}
        </div>
      )}
      <VaultDialog
        open={dialog.open}
        vault={dialog.vault}
        onClose={(saved) => {
          setDialog({ open: false });
          if (saved) refreshVaults();
        }}
      />
    </>
  );
}

function VaultCard({ vault, go, onEdit }: { vault: Vault; go: (r: Route) => void; onEdit: () => void }) {
  const styles = useStyles();
  const { refreshVaults, notify } = useStore();
  const jobs = useActiveJobs(vault.id);
  const [dragging, setDragging] = useState(false);
  const errors = vault.stats.by_status.error ?? 0;

  async function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (!isDesktop) return;
    const paths = [...e.dataTransfer.files].map((f) => window.wsos!.pathForFile(f)).filter(Boolean);
    if (paths.length) {
      await api.ingest(vault.id, paths);
      notify(`${paths.length} elementi aggiunti alla coda di "${vault.name}"`, "info");
    }
  }

  async function remove() {
    if (!confirm(`Eliminare il Vault "${vault.name}"? Vengono cancellati solo l'indice e i vettori: i documenti originali restano dove sono.`)) return;
    await api.deleteVault(vault.id);
    notify("Vault eliminato", "success");
    refreshVaults();
  }

  return (
    <Card
      className={dragging ? styles.drop : undefined}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <CardHeader
        image={<DatabaseRegular fontSize={28} />}
        header={
          <Text weight="semibold" size={400} style={{ cursor: "pointer" }} onClick={() => go({ page: "vault", id: vault.id })}>
            {vault.name}
          </Text>
        }
        description={<Caption1>{modelLabel(vault.embedding)}{vault.dimension ? ` · ${vault.dimension} dim` : ""}</Caption1>}
        action={
          <Menu>
            <MenuTrigger disableButtonEnhancement>
              <Button appearance="subtle" icon={<MoreHorizontalRegular />} aria-label="Altre azioni" />
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <MenuItem icon={<EditRegular />} onClick={onEdit}>Modifica</MenuItem>
                <MenuItem icon={<ArrowSyncRegular />} onClick={() => api.sync(vault.id, true)}>Ricostruisci da zero</MenuItem>
                <MenuItem icon={<DeleteRegular />} onClick={remove}>Elimina Vault</MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        }
      />
      {vault.description && <Body1>{vault.description}</Body1>}
      <div className={styles.stats}>
        <Stat label="File" value={vault.stats.files} />
        <Stat label="Chunk" value={vault.stats.vectors} />
        <Stat label="Pagine OCR" value={vault.stats.ocr_pages} />
        <Stat label="Dimensione" value={formatBytes(vault.stats.bytes)} />
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <Badge appearance="tint" color={vault.chunking.strategy === "semantic" ? "important" : "informative"}>
          {vault.chunking.strategy === "semantic" ? "Semantico" : `Ricorsivo ${vault.chunking.chunk_size}/${vault.chunking.chunk_overlap}`}
        </Badge>
        <Badge appearance="tint">{vault.metric}</Badge>
        {vault.contextual_summary && <Badge appearance="tint" color="brand">Contestuale</Badge>}
        {errors > 0 && (
          <Badge appearance="filled" color="danger" style={{ cursor: "pointer" }} onClick={() => go({ page: "vault", id: vault.id })}>
            {errors} errori
          </Badge>
        )}
      </div>
      <Caption1 truncate wrap={false} title={vault.sources.join("\n")}>
        {vault.sources.length ? vault.sources.join(" · ") : "Nessuna cartella sorgente (solo drag & drop)"}
      </Caption1>
      {jobs.map((j) => (
        <JobProgress key={j.id} job={j} />
      ))}
      <CardFooter
        action={
          <Switch
            checked={vault.watch}
            label={vault.watching ? "Live-watching attivo" : "Live-watching"}
            onChange={async (_, d) => {
              await api.updateVault(vault.id, { watch: d.checked });
              refreshVaults();
            }}
          />
        }
      >
        <Button icon={<ArrowSyncRegular />} disabled={vault.busy} onClick={() => api.sync(vault.id)}>
          Sincronizza
        </Button>
        <Button icon={<SearchRegular />} onClick={() => go({ page: "search", id: vault.id })}>
          Testa ricerca
        </Button>
      </CardFooter>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  const styles = useStyles();
  return (
    <div className={styles.stat}>
      <span className={styles.num}>{value}</span>
      <Caption1>{label}</Caption1>
    </div>
  );
}
