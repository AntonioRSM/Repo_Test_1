import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, subscribeEvents, type AgentEvent, type AppSettings, type HardwareSample, type Job, type OllamaEvent, type ProviderStatus, type Vault } from "./api";

const HISTORY = 90; // seconds of hardware history kept for the charts

interface Store {
  vaults: Vault[];
  jobs: Record<string, Job>;
  providers: ProviderStatus[];
  settings: AppSettings | null;
  hardware: HardwareSample[];
  refreshVaults(): Promise<void>;
  refreshProviders(): Promise<void>;
  setSettings(s: AppSettings): void;
  notify(message: string, intent?: "success" | "error" | "info"): void;
  toast: { message: string; intent: "success" | "error" | "info"; id: number } | null;
  onAgentEvent(listener: (e: AgentEvent) => void): () => void;
  onOllamaEvent(listener: (e: OllamaEvent) => void): () => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [vaults, setVaults] = useState<Vault[]>([]);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [hardware, setHardware] = useState<HardwareSample[]>([]);
  const [toast, setToast] = useState<Store["toast"]>(null);
  const refreshTimer = useRef<number | null>(null);
  const agentListeners = useRef(new Set<(e: AgentEvent) => void>());
  const ollamaListeners = useRef(new Set<(e: OllamaEvent) => void>());
  const onAgentEvent = useCallback((listener: (e: AgentEvent) => void) => {
    agentListeners.current.add(listener);
    return () => {
      agentListeners.current.delete(listener);
    };
  }, []);
  const onOllamaEvent = useCallback((listener: (e: OllamaEvent) => void) => {
    ollamaListeners.current.add(listener);
    return () => {
      ollamaListeners.current.delete(listener);
    };
  }, []);

  const refreshVaults = useCallback(async () => setVaults(await api.vaults()), []);
  const refreshProviders = useCallback(async () => setProviders(await api.providers()), []);
  const notify = useCallback((message: string, intent: "success" | "error" | "info" = "info") => {
    setToast({ message, intent, id: Date.now() });
  }, []);

  useEffect(() => {
    refreshVaults();
    refreshProviders();
    api.settings().then(setSettings);
    api.jobs().then((list) => setJobs(Object.fromEntries(list.map((j) => [j.id, j]))));

    // Vault stats change with every processed file; coalesce refreshes.
    const scheduleVaultRefresh = () => {
      if (refreshTimer.current) return;
      refreshTimer.current = window.setTimeout(() => {
        refreshTimer.current = null;
        refreshVaults();
      }, 700);
    };
    const unsubscribe = subscribeEvents((event) => {
      if (event.type === "agent") {
        agentListeners.current.forEach((listener) => listener(event));
      } else if (event.type === "ollama") {
        ollamaListeners.current.forEach((listener) => listener(event));
      } else if (event.type === "job") {
        setJobs((prev) => ({ ...prev, [event.job.id]: event.job }));
        scheduleVaultRefresh();
      } else {
        scheduleVaultRefresh();
      }
    });

    const hw = window.setInterval(async () => {
      try {
        const sample = await api.hardware();
        setHardware((prev) => [...prev.slice(-(HISTORY - 1)), sample]);
      } catch {
        /* engine restarting */
      }
    }, 1000);
    const prov = window.setInterval(() => refreshProviders().catch(() => undefined), 15000);
    return () => {
      unsubscribe();
      window.clearInterval(hw);
      window.clearInterval(prov);
    };
  }, [refreshVaults, refreshProviders]);

  const value = useMemo<Store>(
    () => ({ vaults, jobs, providers, settings, hardware, refreshVaults, refreshProviders, setSettings, notify, toast, onAgentEvent, onOllamaEvent }),
    [vaults, jobs, providers, settings, hardware, refreshVaults, refreshProviders, notify, toast, onAgentEvent, onOllamaEvent],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const store = useContext(Ctx);
  if (!store) throw new Error("useStore outside StoreProvider");
  return store;
}

export function useActiveJobs(vaultId?: string): Job[] {
  const { jobs } = useStore();
  return Object.values(jobs)
    .filter((j) => (j.status === "running" || j.status === "queued") && (!vaultId || j.vault_id === vaultId))
    .sort((a, b) => a.created_at - b.created_at);
}

export function useModels(kind: "embedding" | "llm" | "vision") {
  const { providers } = useStore();
  return providers.flatMap((p) =>
    p.online ? p.models.filter((m) => m.kinds.includes(kind)).map((m) => ({ provider: p.provider, model: m.id, loaded: m.loaded })) : [],
  );
}
