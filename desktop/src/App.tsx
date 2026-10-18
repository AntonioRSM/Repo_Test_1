import {
  Badge,
  Caption1,
  makeStyles,
  Tab,
  TabList,
  Text,
  Toast,
  Toaster,
  ToastTitle,
  tokens,
  useId,
  useToastController,
} from "@fluentui/react-components";
import {
  BoardRegular,
  BotRegular,
  DatabaseRegular,
  DataScatterRegular,
  SearchRegular,
  SettingsRegular,
} from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { isDesktop } from "./api";
import AgentPage from "./pages/Agent";
import Dashboard from "./pages/Dashboard";
import Explorer from "./pages/Explorer";
import SearchPage from "./pages/Search";
import SettingsPage from "./pages/Settings";
import VaultDetail from "./pages/VaultDetail";
import Vaults from "./pages/Vaults";
import { useActiveJobs, useStore } from "./store";

export type Route =
  | { page: "dashboard" }
  | { page: "agent" }
  | { page: "vaults" }
  | { page: "vault"; id: string }
  | { page: "explorer"; id?: string }
  | { page: "search"; id?: string }
  | { page: "settings" };

const useStyles = makeStyles({
  shell: { display: "grid", gridTemplateColumns: "232px 1fr", gridTemplateRows: "40px 1fr", height: "100%" },
  titlebar: {
    gridColumn: "1 / 3",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    paddingLeft: "16px",
    // Lets the user drag the frameless window by its title bar.
    ["WebkitAppRegion" as string]: "drag",
    userSelect: "none",
  },
  logo: { width: "18px", height: "18px" },
  nav: { padding: "8px 8px 16px", display: "flex", flexDirection: "column", justifyContent: "space-between" },
  content: {
    overflow: "auto",
    padding: "24px 32px",
    borderTopLeftRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
  },
  footer: { padding: "0 12px", display: "flex", flexDirection: "column", gap: "4px" },
});

export default function App({ dark }: { dark: boolean }) {
  const styles = useStyles();
  const [route, setRoute] = useState<Route>({ page: "dashboard" });
  const store = useStore();
  const active = useActiveJobs();
  const toasterId = useId("toaster");
  const { dispatchToast } = useToastController(toasterId);

  useEffect(() => {
    if (store.toast) {
      dispatchToast(
        <Toast>
          <ToastTitle>{store.toast.message}</ToastTitle>
        </Toast>,
        { intent: store.toast.intent, timeout: 4000 },
      );
    }
  }, [store.toast, dispatchToast]);

  const tab = route.page === "vault" ? "vaults" : route.page;
  const online = store.providers.filter((p) => p.online);

  return (
    <div className={styles.shell} style={{ background: isDesktop ? "transparent" : dark ? "#202020" : "#f3f3f3" }}>
      <div className={styles.titlebar}>
        <img className={styles.logo} src="./assets/icon.png" alt="" onError={(e) => (e.currentTarget.style.display = "none")} />
        <Text weight="semibold">RAG Vault Studio</Text>
        <Caption1>Workspace OS</Caption1>
      </div>
      <nav className={styles.nav}>
        <TabList vertical selectedValue={tab} onTabSelect={(_, d) => setRoute({ page: d.value as "dashboard" })} size="large">
          <Tab value="dashboard" icon={<BoardRegular />}>Dashboard</Tab>
          <Tab value="agent" icon={<BotRegular />}>Agente</Tab>
          <Tab value="vaults" icon={<DatabaseRegular />}>
            Vault {active.length > 0 && <Badge size="small" appearance="filled" color="brand">{active.length}</Badge>}
          </Tab>
          <Tab value="explorer" icon={<DataScatterRegular />}>Esplora vettori</Tab>
          <Tab value="search" icon={<SearchRegular />}>Search &amp; Retrieval</Tab>
          <Tab value="settings" icon={<SettingsRegular />}>Impostazioni</Tab>
        </TabList>
        <div className={styles.footer}>
          {store.providers.map((p) => (
            <Caption1 key={p.provider}>
              <Badge size="tiny" color={p.online ? "success" : "subtle"} /> {p.provider === "lmstudio" ? "LM Studio" : "Ollama"}{" "}
              {p.online ? `· ${p.models.length} modelli` : "· offline"}
            </Caption1>
          ))}
          {online.length === 0 && <Caption1>Nessun server LLM locale attivo</Caption1>}
        </div>
      </nav>
      <main className={styles.content}>
        {route.page === "dashboard" && <Dashboard go={setRoute} />}
        {route.page === "agent" && <AgentPage />}
        {route.page === "vaults" && <Vaults go={setRoute} />}
        {route.page === "vault" && <VaultDetail id={route.id} go={setRoute} />}
        {route.page === "explorer" && <Explorer initialId={route.id} />}
        {route.page === "search" && <SearchPage initialId={route.id} />}
        {route.page === "settings" && <SettingsPage />}
      </main>
      <Toaster toasterId={toasterId} position="bottom-end" />
    </div>
  );
}
