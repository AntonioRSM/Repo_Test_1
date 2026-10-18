import { tokens } from "@fluentui/react-components";
import { useMemo, useState } from "react";

/** Categorical palette tuned for both light and dark Fluent themes. */
export const PALETTE = ["#0f6cbd", "#c239b3", "#13a10e", "#da3b01", "#8764b8", "#038387", "#ca5010", "#4f6bed", "#e3008c", "#498205"];

export function Sparkline({
  values,
  max = 100,
  color = tokens.colorBrandForeground1,
  height = 56,
  label,
}: {
  values: number[];
  max?: number;
  color?: string;
  height?: number;
  label: string;
}) {
  const width = 240;
  const points = values.length > 1 ? values : [0, ...values];
  const step = width / Math.max(points.length - 1, 1);
  const y = (v: number) => height - (Math.min(v, max) / max) * (height - 4) - 2;
  const line = points.map((v, i) => `${i * step},${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={label} preserveAspectRatio="none">
      <polygon points={`0,${height} ${line} ${(points.length - 1) * step},${height}`} fill={color} opacity={0.15} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export interface ScatterPoint {
  id: string;
  x: number;
  y: number;
  group: string;
  label: string;
}

export function Scatter({ points, onSelect, height = 460 }: { points: ScatterPoint[]; onSelect?: (p: ScatterPoint) => void; height?: number }) {
  const [hover, setHover] = useState<ScatterPoint | null>(null);
  const { groups, sx, sy } = useMemo(() => {
    const groups = [...new Set(points.map((p) => p.group))];
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const pad = 24;
    const sx = (v: number) => pad + ((v - minX) / (maxX - minX || 1)) * (1000 - 2 * pad);
    const sy = (v: number) => pad + ((v - minY) / (maxY - minY || 1)) * (height - 2 * pad);
    return { groups, sx, sy };
  }, [points, height]);
  const color = (g: string) => PALETTE[groups.indexOf(g) % PALETTE.length];

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 1000 ${height}`} width="100%" height={height} role="img" aria-label="Proiezione 2D dei vettori (PCA)">
        <rect x={0} y={0} width={1000} height={height} fill="none" stroke={tokens.colorNeutralStroke2} rx={8} />
        {points.map((p) => (
          <circle
            key={p.id}
            cx={sx(p.x)}
            cy={sy(p.y)}
            r={hover?.id === p.id ? 7 : 4.5}
            fill={color(p.group)}
            fillOpacity={0.8}
            stroke={hover?.id === p.id ? tokens.colorNeutralForeground1 : "none"}
            style={{ cursor: "pointer" }}
            onMouseEnter={() => setHover(p)}
            onMouseLeave={() => setHover(null)}
            onClick={() => onSelect?.(p)}
          />
        ))}
      </svg>
      {hover && (
        <div
          style={{
            position: "absolute",
            left: `${(sx(hover.x) / 1000) * 100}%`,
            top: sy(hover.y) + 12,
            maxWidth: 360,
            padding: "8px 10px",
            borderRadius: 6,
            background: tokens.colorNeutralBackground1,
            boxShadow: tokens.shadow16,
            fontSize: 12,
            pointerEvents: "none",
            zIndex: 2,
          }}
        >
          <strong>{hover.group}</strong>
          <div>{hover.label}</div>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 14px", marginTop: 8, fontSize: 12 }}>
        {groups.slice(0, 30).map((g) => (
          <span key={g} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 5, background: color(g) }} />
            {g}
          </span>
        ))}
      </div>
    </div>
  );
}
