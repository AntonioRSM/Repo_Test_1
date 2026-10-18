import { FluentProvider, Spinner, webDarkTheme, webLightTheme, MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { connectEngine } from "./api";
import App from "./App";
import { StoreProvider } from "./store";

function useSystemDark() {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const [dark, setDark] = useState(query.matches);
  useEffect(() => {
    const onChange = () => setDark(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [query]);
  return dark;
}

function Root() {
  const dark = useSystemDark();
  const [state, setState] = useState<{ ok: boolean; error?: string } | null>(null);

  useEffect(() => {
    connectEngine().then(setState);
  }, []);
  useEffect(() => {
    window.wsos?.setTitleBarSymbolColor(dark ? "#ffffff" : "#000000");
  }, [dark]);

  const theme = dark ? webDarkTheme : webLightTheme;
  return (
    // Transparent so the Windows 11 Mica material shows through the window.
    <FluentProvider theme={theme} style={{ height: "100%", background: "transparent" }}>
      {state === null && (
        <div style={{ display: "grid", placeItems: "center", height: "100%" }}>
          <Spinner label="Avvio del motore RAG locale…" />
        </div>
      )}
      {state && !state.ok && (
        <div style={{ padding: 48 }}>
          <MessageBar intent="error">
            <MessageBarBody>
              <MessageBarTitle>Motore non disponibile</MessageBarTitle>
              {state.error}
            </MessageBarBody>
          </MessageBar>
        </div>
      )}
      {state?.ok && (
        <StoreProvider>
          <App dark={dark} />
        </StoreProvider>
      )}
    </FluentProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
