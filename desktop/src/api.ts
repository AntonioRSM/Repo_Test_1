// Typed client for the local vault engine.

export type ProviderKind = "lmstudio" | "ollama";
export type ModelKind = "embedding" | "llm" | "vision";
export type Metric = "cosine" | "dot" | "l2";

export interface ModelRef { provider: ProviderKind; model: string }
export interface ModelInfo { id: string; kinds: ModelKind[]; loaded: boolean | null; size_bytes: number | null; context_length: number | null }
export interface ProviderStatus { provider: ProviderKind; base_url: string; online: boolean; version: string | null; models: ModelInfo[]; error: string | null }

export interface OcrSettings {
  engine: "rapidocr" | "tesseract" | "vision" | "none";
  vision: ModelRef | null;
  min_text_chars_per_page: number;
  languages: string[];
}
export interface AppSettings {
  endpoints: Record<ProviderKind, string>;
  default_embedding: ModelRef | null;
  llm: ModelRef | null;
  ocr: OcrSettings;
  ingest_workers: number;
  embed_batch_size: number;
  agent_max_steps: number;
  agent_max_tokens: number;
  agent_reasoning: boolean;
}
export interface ChunkingSettings {
  strategy: "recursive" | "semantic";
  chunk_size: number;
  chunk_overlap: number;
  breakpoint_percentile: number;
  min_chunk_size: number;
}
export interface VaultStats { files: number; by_status: Record<string, number>; chunks: number; bytes: number; ocr_pages: number; vectors: number }
export interface Vault {
  id: string;
  name: string;
  description: string;
  sources: string[];
  embedding: ModelRef;
  chunking: ChunkingSettings;
  ocr: OcrSettings | null;
  parser: "builtin" | "docling";
  contextual_summary: boolean;
  watch: boolean;
  metric: Metric;
  dimension: number | null;
  created_at: string;
  stats: VaultStats;
  busy: boolean;
  watching: boolean;
}
export type VaultInput = Pick<Vault, "name" | "description" | "sources" | "embedding" | "chunking" | "ocr" | "parser" | "contextual_summary" | "watch" | "metric">;

export interface FileRecord {
  path: string; source: string | null; sha256: string | null; size: number; mtime: number;
  status: "pending" | "indexed" | "error" | "skipped"; chunks: number; error: string | null;
  title: string | null; author: string | null; created: string | null; modified: string | null;
  language: string | null; pages: number | null; ocr_pages: number; ocr_engine: string | null; updated_at: number;
}
export interface Job {
  id: string; vault_id: string; kind: "sync" | "ingest" | "remove" | "rebuild";
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  total: number; done: number; skipped: number; failed: number; removed: number;
  current: string | null; message: string | null; created_at: number; started_at: number | null; finished_at: number | null;
}
export interface GpuSample { name: string; utilization_pct: number; dedicated_used_mb: number | null; dedicated_total_mb: number | null; shared_used_mb: number | null }
export interface HardwareSample { timestamp: number; cpu_pct: number; cpu_count: number; ram_used_mb: number; ram_total_mb: number; process_rss_mb: number; gpus: GpuSample[] }
export interface ChunkRow {
  id: string; text: string; file_path: string; file_name: string; chunk_index: number; heading: string;
  page_start: number | null; page_end: number | null; title: string | null; author: string | null; language: string | null; ocr: boolean;
}
export interface SearchHit extends ChunkRow {
  _distance: number;
  scores: { cosine: number; dot: number; euclidean: number };
  rerank_score?: number | null;
}
export interface ProjectionPoint { id: string; x: number; y: number; file_name: string; chunk_index: number; preview: string }

export interface ToolCall { id: string; name: string; arguments: string }
export interface AgentMessage {
  id: string;
  thread_id: string;
  seq: number;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls: ToolCall[] | null;
  tool_call_id: string | null;
  name: string | null;
  meta: Record<string, unknown>;
  created_at: number;
}
export interface AgentTask { id: string; content: string; status: "pending" | "in_progress" | "completed" }
export interface PendingCall { id: string; name: string; arguments: Record<string, unknown> | string; risk?: string }
export interface AgentThread {
  id: string;
  title: string;
  model: ModelRef | null;
  vault_ids: string[];
  auto_approve: string[];
  tasks: AgentTask[];
  created_at: number;
  updated_at: number;
  status: { running: boolean; step?: number; pending: { id: string; name: string; arguments: string }[] };
  messages?: AgentMessage[];
}
export type AgentEvent = { type: "agent"; thread_id: string } & (
  | { kind: "run_started" }
  | { kind: "thinking"; step: number }
  | { kind: "delta"; text: string }
  | { kind: "message"; message: AgentMessage }
  | { kind: "approval"; call: PendingCall }
  | { kind: "approval_resolved"; call_id: string; decision: string }
  | { kind: "tool_started"; call_id: string; name: string }
  | { kind: "run_finished"; seconds?: number; error?: string; cancelled?: boolean }
);

export type EngineEvent =
  | { type: "job"; job: Job }
  | { type: "file"; vault_id: string; path: string; status: string; chunks?: number; error?: string | null }
  | AgentEvent;

declare global {
  interface Window {
    wsos?: {
      engineInfo(): Promise<{ port: number | null; token: string; error: string | null }>;
      engineLog(): Promise<string[]>;
      onEngineStatus(listener: (info: { port: number | null; token: string; error: string | null }) => void): () => void;
      pickFolders(): Promise<string[]>;
      openPath(target: string): Promise<string>;
      showInFolder(target: string): Promise<void>;
      setTitleBarSymbolColor(color: string): Promise<void>;
      pathForFile(file: File): string;
    };
  }
}

export const isDesktop = typeof window !== "undefined" && !!window.wsos;

let base = "";
let token = "";

/** Desktop: ask the main process. Browser preview: ?port=…&token=… or the default dev port. */
export async function connectEngine(): Promise<{ ok: boolean; error?: string }> {
  if (window.wsos) {
    for (let i = 0; i < 200; i++) {
      const info = await window.wsos.engineInfo();
      if (info.error) return { ok: false, error: info.error };
      if (info.port) {
        base = `http://127.0.0.1:${info.port}`;
        token = info.token;
        return { ok: true };
      }
      await new Promise((r) => setTimeout(r, 150));
    }
    return { ok: false, error: "Il motore non si è avviato" };
  }
  const params = new URLSearchParams(location.search);
  base = `http://127.0.0.1:${params.get("port") ?? "8765"}`;
  token = params.get("token") ?? "";
  try {
    await fetch(`${base}/health`);
    return { ok: true };
  } catch {
    return { ok: false, error: `Motore non raggiungibile su ${base}` };
  }
}

export class ApiError extends Error {}

async function call<T>(method: string, route: string, body?: unknown): Promise<T> {
  const res = await fetch(base + route, {
    method,
    headers: { "content-type": "application/json", ...(token ? { "x-wsos-token": token } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* no JSON body */
    }
    throw new ApiError(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
};

export const api = {
  providers: () => call<ProviderStatus[]>("GET", "/providers"),
  hardware: () => call<HardwareSample>("GET", "/hardware"),
  settings: () => call<AppSettings>("GET", "/settings"),
  updateSettings: (patch: Partial<AppSettings>) => call<AppSettings>("PATCH", "/settings", patch),
  testEmbedding: (embedding: ModelRef) => call<{ dimension: number; preview: number[] }>("POST", "/providers/test-embedding", { embedding }),
  vaults: () => call<Vault[]>("GET", "/vaults"),
  vault: (id: string) => call<Vault>("GET", `/vaults/${id}`),
  createVault: (input: VaultInput) => call<Vault>("POST", "/vaults", input),
  updateVault: (id: string, patch: Partial<VaultInput>) => call<Vault>("PATCH", `/vaults/${id}`, patch),
  deleteVault: (id: string) => call<void>("DELETE", `/vaults/${id}`),
  sync: (id: string, rebuild = false) => call<Job>("POST", `/vaults/${id}/sync${q({ rebuild: rebuild ? "true" : undefined })}`),
  ingest: (id: string, paths: string[]) => call<Job>("POST", `/vaults/${id}/ingest`, { paths }),
  files: (id: string, opts: { status?: string; q?: string; offset?: number; limit?: number } = {}) =>
    call<FileRecord[]>("GET", `/vaults/${id}/files${q(opts)}`),
  removeFile: (id: string, path: string) => call<void>("DELETE", `/vaults/${id}/files${q({ path })}`),
  chunks: (id: string, opts: { file?: string; offset?: number; limit?: number } = {}) =>
    call<{ total: number; items: ChunkRow[] }>("GET", `/vaults/${id}/chunks${q(opts)}`),
  projection: (id: string, limit = 2000) => call<ProjectionPoint[]>("GET", `/vaults/${id}/projection${q({ limit })}`),
  jobs: (vaultId?: string) => call<Job[]>("GET", `/jobs${q({ vault_id: vaultId })}`),
  cancelJob: (id: string) => call<void>("POST", `/jobs/${id}/cancel`),
  search: (id: string, body: { query: string; k: number; metric?: Metric; rerank?: boolean }) =>
    call<{ metric: Metric; results: SearchHit[]; rerank_error: string | null }>("POST", `/vaults/${id}/search`, body),
  threads: () => call<AgentThread[]>("GET", "/agent/threads"),
  thread: (id: string) => call<AgentThread>("GET", `/agent/threads/${id}`),
  createThread: (body: { model?: ModelRef | null; vault_ids?: string[] } = {}) => call<AgentThread>("POST", "/agent/threads", body),
  updateThread: (id: string, patch: Partial<Pick<AgentThread, "title" | "model" | "vault_ids" | "auto_approve">>) =>
    call<AgentThread>("PATCH", `/agent/threads/${id}`, patch),
  deleteThread: (id: string) => call<void>("DELETE", `/agent/threads/${id}`),
  sendMessage: (id: string, content: string) => call<{ accepted: boolean }>("POST", `/agent/threads/${id}/messages`, { content }),
  approve: (id: string, callId: string, decision: "allow" | "allow_always" | "deny", note?: string) =>
    call<void>("POST", `/agent/threads/${id}/approvals/${callId}`, { decision, note }),
  cancelRun: (id: string) => call<void>("POST", `/agent/threads/${id}/cancel`),
  ask: (id: string, body: { query: string; k: number; rerank?: boolean }) =>
    call<{ answer: string; sources: SearchHit[]; rerank_error: string | null }>("POST", `/vaults/${id}/ask`, body),
};

export function subscribeEvents(onEvent: (e: EngineEvent) => void): () => void {
  const source = new EventSource(`${base}/events${q({ token })}`);
  source.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data));
    } catch {
      /* ignore malformed */
    }
  };
  return () => source.close();
}

export const formatBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 2 ** 20 ? `${(n / 1024).toFixed(1)} KB` : n < 2 ** 30 ? `${(n / 2 ** 20).toFixed(1)} MB` : `${(n / 2 ** 30).toFixed(2)} GB`;

export const modelLabel = (ref: ModelRef | null | undefined) =>
  ref ? `${ref.provider === "lmstudio" ? "LM Studio" : "Ollama"} · ${ref.model}` : "—";

export const providerName = (p: ProviderKind) => (p === "lmstudio" ? "LM Studio" : "Ollama");
