import { Body1, Button, Caption1, Card, makeStyles, Spinner, Text, Title3, tokens } from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { api, type ChunkRow, type ProjectionPoint } from "../api";
import { Scatter } from "../components/Charts";
import { VaultPicker } from "../components/VaultPicker";
import { useStore } from "../store";

const PAGE = 25;

const useStyles = makeStyles({
  layout: { display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(320px, 2fr)", gap: "16px", alignItems: "start" },
  chunk: { padding: "10px 12px", borderRadius: tokens.borderRadiusMedium, background: tokens.colorNeutralBackground3, whiteSpace: "pre-wrap", fontSize: "13px" },
});

export default function Explorer({ initialId }: { initialId?: string }) {
  const styles = useStyles();
  const { vaults } = useStore();
  const [vaultId, setVaultId] = useState<string | undefined>(initialId ?? vaults[0]?.id);
  const [points, setPoints] = useState<ProjectionPoint[] | null>(null);
  const [rows, setRows] = useState<{ total: number; items: ChunkRow[] }>({ total: 0, items: [] });
  const [offset, setOffset] = useState(0);
  const [focus, setFocus] = useState<ProjectionPoint | null>(null);

  useEffect(() => {
    if (!vaultId && vaults[0]) setVaultId(vaults[0].id);
  }, [vaults, vaultId]);

  useEffect(() => {
    if (!vaultId) return;
    setPoints(null);
    setFocus(null);
    api.projection(vaultId).then(setPoints);
  }, [vaultId]);

  useEffect(() => {
    if (vaultId) api.chunks(vaultId, { offset, limit: PAGE }).then(setRows);
  }, [vaultId, offset]);

  return (
    <>
      <Title3 as="h1">Esplora vettori</Title3>
      <Body1 as="p" style={{ color: tokens.colorNeutralForeground3 }}>
        Proiezione 2D (PCA) degli embedding: chunk vicini hanno significato simile. I colori indicano il documento di origine.
      </Body1>
      <VaultPicker value={vaultId} onChange={(id) => { setVaultId(id); setOffset(0); }} />
      <div className={styles.layout} style={{ marginTop: 16 }}>
        <Card>
          {points === null ? (
            <Spinner label="Calcolo della proiezione…" />
          ) : points.length === 0 ? (
            <Caption1>Nessun vettore in questo Vault.</Caption1>
          ) : (
            <Scatter
              points={points.map((p) => ({ id: p.id, x: p.x, y: p.y, group: p.file_name, label: `#${p.chunk_index} · ${p.preview}` }))}
              onSelect={(p) => setFocus(points.find((x) => x.id === p.id) ?? null)}
            />
          )}
          {focus && (
            <div style={{ marginTop: 12 }}>
              <Text weight="semibold">{focus.file_name} · chunk #{focus.chunk_index}</Text>
              <div className={styles.chunk}>{focus.preview}…</div>
            </div>
          )}
        </Card>
        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Text weight="semibold">Chunk memorizzati</Text>
            <Caption1>
              {rows.total ? `${offset + 1}–${Math.min(offset + PAGE, rows.total)} di ${rows.total}` : "0"}
            </Caption1>
          </div>
          <div style={{ display: "grid", gap: 10, maxHeight: 560, overflow: "auto" }}>
            {rows.items.map((c) => (
              <div key={c.id}>
                <Caption1>
                  {c.file_name} · #{c.chunk_index}
                  {c.heading && ` · ${c.heading}`}
                  {c.page_start && ` · p. ${c.page_start}`}
                  {c.ocr && " · OCR"}
                </Caption1>
                <div className={styles.chunk}>{c.text.length > 600 ? c.text.slice(0, 600) + "…" : c.text}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Precedenti</Button>
            <Button disabled={offset + PAGE >= rows.total} onClick={() => setOffset(offset + PAGE)}>Successivi</Button>
          </div>
        </Card>
      </div>
    </>
  );
}
