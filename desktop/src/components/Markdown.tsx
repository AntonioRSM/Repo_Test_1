import { tokens } from "@fluentui/react-components";
import { Fragment, type ReactNode } from "react";

// Minimal Markdown → React renderer. Model output is never injected as HTML.

function openLink(url: string) {
  window.open(url, "_blank", "noopener"); // Electron routes this to the default browser
}

function inline(raw: string, key = 0): ReactNode[] {
  // Backslash escapes (modulo\_ferie) render as the literal character.
  const text = raw.replace(/\\([\\`*_{}[\]()#+\-.!|])/g, "$1");
  const out: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[[^\]]+\]\((https?:\/\/[^)\s]+)\)|https?:\/\/[^\s)]+)/g;
  let last = 0;
  let i = 0;
  for (const match of text.matchAll(pattern)) {
    const [token] = match;
    if (match.index! > last) out.push(text.slice(last, match.index));
    const k = `${key}-${i++}`;
    if (token.startsWith("`")) {
      out.push(<code key={k} style={{ fontFamily: "Cascadia Code, Consolas, monospace", background: tokens.colorNeutralBackground3, padding: "0 4px", borderRadius: 4 }}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      out.push(<strong key={k}>{inline(token.slice(2, -2), i)}</strong>);
    } else if (token.startsWith("[")) {
      const label = token.slice(1, token.indexOf("]"));
      const url = match[2]!;
      out.push(<a key={k} href={url} onClick={(e) => { e.preventDefault(); openLink(url); }}>{label}</a>);
    } else if (token.startsWith("http")) {
      out.push(<a key={k} href={token} onClick={(e) => { e.preventDefault(); openLink(token); }}>{token}</a>);
    } else {
      out.push(<em key={k}>{token.slice(1, -1)}</em>);
    }
    last = match.index! + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function table(lines: string[], key: number) {
  const rows = lines
    .map((l) => l.replace(/^\||\|$/g, "").split("|").map((c) => c.trim()))
    .filter((cells) => !cells.every((c) => /^:?-+:?$/.test(c))); // drop the |---|---| separator
  const body = rows.slice(1);
  return (
    <table key={key} style={{ borderCollapse: "collapse", margin: "8px 0", fontSize: 13 }}>
      <thead>
        <tr>{rows[0].map((c, i) => <th key={i} style={{ textAlign: "left", borderBottom: `1px solid ${tokens.colorNeutralStroke1}`, padding: "4px 10px" }}>{inline(c)}</th>)}</tr>
      </thead>
      <tbody>
        {body.map((r, ri) => (
          <tr key={ri}>{r.map((c, i) => <td key={i} style={{ borderBottom: `1px solid ${tokens.colorNeutralStroke2}`, padding: "4px 10px" }}>{inline(c)}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/<think>[\s\S]*?(<\/think>|$)/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={i} style={{ background: tokens.colorNeutralBackground3, padding: 10, borderRadius: 6, overflowX: "auto", fontSize: 12.5, fontFamily: "Cascadia Code, Consolas, monospace" }}>
          {code.join("\n")}
        </pre>,
      );
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)/);
    if (heading) {
      const size = [0, 20, 17, 15, 14][heading[1].length];
      blocks.push(<div key={i} style={{ fontSize: size, fontWeight: 600, margin: "12px 0 4px" }}>{inline(heading[2], i)}</div>);
      i++;
      continue;
    }
    if (line.trim().startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++].trim());
      blocks.push(table(rows, i));
      continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*+]|\d+[.)])\s+/, ""));
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={i} style={{ margin: "4px 0", paddingLeft: 22 }}>{items.map((it, j) => <li key={j}>{inline(it, j)}</li>)}</List>);
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\||\s*([-*+]|\d+[.)])\s)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(
      <p key={i} style={{ margin: "6px 0", lineHeight: 1.55 }}>
        {para.map((p, j) => (
          <Fragment key={j}>{j > 0 && <br />}{inline(p, j)}</Fragment>
        ))}
      </p>,
    );
  }
  return <div>{blocks}</div>;
}
