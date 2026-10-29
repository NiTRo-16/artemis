// The signed-in account, the visitor's settings and the account dialogs, shared by every page.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import * as backend from "./api";
import type { Account, Settings } from "./types";

const SETTINGS_KEY = "artemis.settings";
const DEFAULT_SETTINGS: Settings = { theme: "system", same_tab: false };

export type AuthMode = "signup" | "login" | "forgot" | "verify" | "reset";

interface AccountState {
  account: Account | null;
  googleSignin: boolean;
  settings: Settings;
  /** Apply settings here and, when signed in, save them to the account too. */
  saveSettings: (next: Settings) => Promise<void>;
  /** Apply settings without saving them to the account (an existing account's settings win). */
  applySettings: (next: Settings) => void;
  setAccount: (account: Account | null) => void;
  auth: { mode: AuthMode; token: string; error: string } | null;
  openAuth: (mode: AuthMode, token?: string, error?: string) => void;
  closeAuth: () => void;
  settingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
}

const Ctx = createContext<AccountState | null>(null);

function loadLocal(): Settings {
  try {
    return clean({ ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") });
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function clean(s: Partial<Settings>): Settings {
  return { theme: s.theme === "light" || s.theme === "dark" ? s.theme : "system", same_tab: !!s.same_tab };
}

export function AccountProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [googleSignin, setGoogleSignin] = useState(false);
  const [settings, setSettings] = useState<Settings>(loadLocal);
  const [auth, setAuth] = useState<AccountState["auth"]>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const applySettings = useCallback((next: Settings) => {
    const s = clean(next);
    setSettings(s);
    if (s.theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = s.theme;
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); } catch { /* storage unavailable */ }
  }, []);

  const saveSettings = useCallback(async (next: Settings) => {
    applySettings(next);
    if (account) {
      try { await backend.putSettings(clean(next)); } catch { /* kept in this browser */ }
    }
  }, [account, applySettings]);

  useEffect(() => { applySettings(settings); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // Who is signed in, and whether the server offers Google sign-in. /?signin=ok|new|failed is where
  // Google sign-in returns; the address bar is cleaned afterwards.
  useEffect(() => {
    const signin = new URLSearchParams(location.search).get("signin");
    if (signin) history.replaceState(null, "", location.pathname);
    backend.me().then((data) => {
      setGoogleSignin(data.google_signin);
      setAccount(data.account);
      if (data.account && signin === "new") void backend.putSettings(settings).catch(() => undefined);
      else if (data.account) applySettings(data.account.settings);
      if (signin === "failed" && !data.account) {
        setAuth({ mode: "login", token: "", error: "Google sign-in didn't work. Try again, or log in with your email and password." });
      }
    }).catch(() => setAccount(null));
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const value = useMemo<AccountState>(() => ({
    account, googleSignin, settings, saveSettings, applySettings, setAccount,
    auth,
    openAuth: (mode, token = "", error = "") => setAuth({ mode, token, error }),
    closeAuth: () => setAuth(null),
    settingsOpen, setSettingsOpen,
  }), [account, googleSignin, settings, saveSettings, applySettings, auth, settingsOpen]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAccount(): AccountState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useAccount outside AccountProvider");
  return value;
}
