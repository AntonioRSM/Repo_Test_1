import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  CardHeader,
  makeStyles,
  Subtitle2,
  Text,
  Title3,
  tokens,
} from "@fluentui/react-components";
import { ArrowSyncRegular, PlugConnectedRegular, PlugDisconnectedRegular } from "@fluentui/react-icons";
import type { Route } from "../App";
import { providerName } from "../api";
import { Sparkline } from "../components/Charts";
import { JobProgress } from "../components/JobProgress";
import { useActiveJobs, useStore } from "../store";

const useStyles = makeStyles({
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "16px", marginBottom: "28px" },
  metric: { display: "flex", alignItems: "baseline", justifyContent: "space-between" },
  big: { fontSize: tokens.fontSizeHero700, fontWeight: tokens.fontWeightSemibold, lineHeight: 1.1 },
  section: { marginTop: "8px", marginBottom: "12px", display: "flex", alignItems: "center", justifyContent: "space-between" },
  models: { display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "8px" },
});

export default function Dashboard({ go }: { go: (r: Route) => void }) {
  const styles = useStyles();
  const { hardware, providers, vaults, refreshProviders } = useStore();
  const active = useActiveJobs();
  const last = hardware[hardware.length - 1];
  const gpu = last?.gpus[0];

  const totals = vaults.reduce(
    (acc, v) => ({ files: acc.files + v.stats.files, vectors: acc.vectors + v.stats.vectors, ocr: acc.ocr + v.stats.ocr_pages }),
    { files: 0, vectors: 0, ocr: 0 },
  );

  return (
    <>
      <Title3 as="h1">Dashboard</Title3>
      <Body1 as="p" style={{ color: tokens.colorNeutralForeground3, marginTop: 4 }}>
        Tutto resta su questo PC: parsing, OCR, embedding e vettori sono elaborati in locale.
      </Body1>

      <div className={styles.section}>
        <Subtitle2>Risorse di sistema</Subtitle2>
      </div>
      <div className={styles.grid}>
        <Card>
          <div className={styles.metric}>
            <Caption1>CPU · {last?.cpu_count ?? "–"} core</Caption1>
            <span className={styles.big}>{last ? Math.round(last.cpu_pct) : "–"}%</span>
          </div>
          <Sparkline label="Utilizzo CPU" values={hardware.map((h) => h.cpu_pct)} />
        </Card>
        <Card>
          <div className={styles.metric}>
            <Caption1>RAM · motore {last ? Math.round(last.process_rss_mb) : "–"} MB</Caption1>
            <span className={styles.big}>{last ? (last.ram_used_mb / 1024).toFixed(1) : "–"} GB</span>
          </div>
          <Sparkline
            label="Utilizzo RAM"
            color={tokens.colorPaletteBerryForeground1}
            values={hardware.map((h) => (h.ram_used_mb / h.ram_total_mb) * 100)}
          />
          <Caption1>su {last ? (last.ram_total_mb / 1024).toFixed(1) : "–"} GB</Caption1>
        </Card>
        <Card>
          <div className={styles.metric}>
            <Caption1 truncate wrap={false} title={gpu?.name}>{gpu?.name ?? "GPU"}</Caption1>
            <span className={styles.big}>{gpu ? Math.round(gpu.utilization_pct) : "–"}%</span>
          </div>
          <Sparkline label="Utilizzo GPU" color={tokens.colorPaletteGreenForeground1} values={hardware.map((h) => h.gpus[0]?.utilization_pct ?? 0)} />
        </Card>
        <Card>
          <div className={styles.metric}>
            <Caption1>VRAM {gpu?.dedicated_total_mb ? "dedicata" : "(dedicata + condivisa)"}</Caption1>
            <span className={styles.big}>
              {gpu ? (((gpu.dedicated_used_mb ?? 0) + (gpu.dedicated_total_mb ? 0 : gpu.shared_used_mb ?? 0)) / 1024).toFixed(1) : "–"} GB
            </span>
          </div>
          <Sparkline
            label="Memoria GPU"
            color={tokens.colorPaletteMarigoldForeground1}
            max={Math.max(1, ...hardware.map((h) => (h.gpus[0]?.dedicated_total_mb ?? 0) || (h.gpus[0]?.dedicated_used_mb ?? 0) + (h.gpus[0]?.shared_used_mb ?? 0)))}
            values={hardware.map((h) => (h.gpus[0]?.dedicated_used_mb ?? 0) + (h.gpus[0]?.dedicated_total_mb ? 0 : h.gpus[0]?.shared_used_mb ?? 0))}
          />
          {gpu?.dedicated_total_mb && <Caption1>su {(gpu.dedicated_total_mb / 1024).toFixed(1)} GB</Caption1>}
        </Card>
      </div>

      <div className={styles.section}>
        <Subtitle2>Server LLM locali</Subtitle2>
        <Button icon={<ArrowSyncRegular />} appearance="subtle" onClick={() => refreshProviders()}>
          Rileva di nuovo
        </Button>
      </div>
      <div className={styles.grid}>
        {providers.map((p) => (
          <Card key={p.provider}>
            <CardHeader
              image={p.online ? <PlugConnectedRegular fontSize={24} /> : <PlugDisconnectedRegular fontSize={24} />}
              header={<Text weight="semibold">{providerName(p.provider)}</Text>}
              description={<Caption1>{p.base_url}{p.version ? ` · v${p.version}` : ""}</Caption1>}
              action={<Badge color={p.online ? "success" : "subtle"}>{p.online ? "Online" : "Offline"}</Badge>}
            />
            {p.online ? (
              <div className={styles.models}>
                {p.models.map((m) => (
                  <Badge key={m.id} appearance={m.loaded ? "filled" : "outline"} color={m.kinds.includes("embedding") ? "informative" : m.kinds.includes("vision") ? "important" : "brand"}>
                    {m.id}
                  </Badge>
                ))}
              </div>
            ) : (
              <Caption1>Avvia {providerName(p.provider)} per usarlo. {p.provider === "ollama" ? "(ollama serve)" : "(Developer → Start Server)"}</Caption1>
            )}
          </Card>
        ))}
      </div>
      <Caption1>
        <Badge size="small" color="informative" /> embedding &nbsp; <Badge size="small" color="brand" /> LLM &nbsp;
        <Badge size="small" color="important" /> vision &nbsp; pieno = caricato in memoria
      </Caption1>

      <div className={styles.section} style={{ marginTop: 28 }}>
        <Subtitle2>
          Archivio · {vaults.length} Vault · {totals.files} file · {totals.vectors} vettori · {totals.ocr} pagine OCR
        </Subtitle2>
        <Button appearance="primary" onClick={() => go({ page: "vaults" })}>Gestisci Vault</Button>
      </div>
      {active.length === 0 ? (
        <Caption1>Nessuna elaborazione in corso.</Caption1>
      ) : (
        active.map((job) => (
          <Card key={job.id} style={{ marginBottom: 8 }}>
            <Text weight="semibold">{vaults.find((v) => v.id === job.vault_id)?.name ?? job.vault_id}</Text>
            <JobProgress job={job} />
          </Card>
        ))
      )}
    </>
  );
}
