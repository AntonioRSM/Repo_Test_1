import { Button, Caption1, ProgressBar } from "@fluentui/react-components";
import { DismissRegular } from "@fluentui/react-icons";
import { api, type Job } from "../api";

const KIND: Record<Job["kind"], string> = {
  sync: "Sincronizzazione",
  ingest: "Ingestione",
  remove: "Rimozione",
  rebuild: "Ricostruzione completa",
};

export function JobProgress({ job }: { job: Job }) {
  const processed = job.done + job.skipped + job.failed;
  const value = job.total ? processed / job.total : undefined;
  const current = job.current ? job.current.split(/[\\/]/).pop() : null;
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <Caption1>
          {KIND[job.kind]} · {job.status === "queued" ? "in coda" : `${processed}/${job.total || "?"}`}
          {job.failed > 0 && ` · ${job.failed} errori`}
          {job.removed > 0 && ` · ${job.removed} rimossi`}
          {current && ` · ${current}`}
        </Caption1>
        <Button size="small" appearance="subtle" icon={<DismissRegular />} aria-label="Annulla" onClick={() => api.cancelJob(job.id)} />
      </div>
      <ProgressBar value={value} thickness="large" />
    </div>
  );
}
