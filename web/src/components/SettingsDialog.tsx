// Settings: theme and how sites open for everyone; account, data and deletion when signed in.
import { useEffect, useState, type FormEvent } from "react";
import { useAccount } from "../account";
import * as backend from "../api";
import { languageOptionShown, tk, useT } from "../i18n";
import type { Settings } from "../types";
import { GlassDialog, GoogleLogo, Icon } from "./ui";

type Section = "appearance" | "browsing" | "account" | "data" | "delete";

const THEMES: [Settings["theme"], string][] = [["system", tk("Match device")], ["light", tk("Light")], ["dark", tk("Dark")]];

export function SettingsDialog() {
  const { settingsOpen, setSettingsOpen, settings, saveSettings, account, setAccount } = useAccount();
  const t = useT();
  const [section, setSection] = useState<Section>("appearance");
  const [saved, setSaved] = useState(false);
  const [note, setNote] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    if (!settingsOpen) { setSection("appearance"); setNote(""); setConfirmText(""); setError(""); setSaved(false); }
  }, [settingsOpen]);
  useEffect(() => { if (!account && ["account", "data", "delete"].includes(section)) setSection("appearance"); }, [account, section]);

  useEffect(() => { setName(account?.name ?? ""); }, [account]);

  const close = () => setSettingsOpen(false);
  const password = !account || account.has_password !== false;   // accounts made with Google may have no password

  async function change(next: Settings) {
    await saveSettings(next);
    setSaved(true);
  }

  async function signOut() {
    try { await backend.logout(); } catch { /* signed out here regardless */ }
    setAccount(null);
    close();
  }

  async function sendReset() {
    if (!account) return;
    try {
      await backend.forgotPassword(account.email);
      setNote(t("We sent a link to {email}. It works for an hour.", { email: account.email }));
    } catch (err) {
      setNote((err as Error).message);
    }
  }

  async function saveName(event: FormEvent) {
    event.preventDefault();
    if (!account) return;
    try {
      const changed = await backend.putName(name);
      setAccount({ ...account, name: changed.name });
      setNote(t("Name saved."));
    } catch (err) {
      setNote((err as Error).message);
    }
  }

  async function clear() {
    if (!window.confirm(t("Delete your whole scan history?"))) return;
    try { await backend.clearHistory(); setNote(t("Your scan history was deleted.")); }
    catch (err) { setNote((err as Error).message); }
  }

  async function remove(event: FormEvent) {
    event.preventDefault();
    try {
      await backend.deleteAccount(confirmText);
      setAccount(null);
      close();
    } catch (err) {
      setError((err as Error).message);
    }
  }
  const links: [Section, string, string][] = [["appearance", tk("Appearance"), "sun"], ["browsing", tk("Opening sites"), "globe"],
    ...(account ? [["account", tk("Account"), "user"], ["data", tk("Your data"), "shield"]] as [Section, string, string][] : [])];

  return (
    <GlassDialog open={settingsOpen} onClose={close} label={t("Settings")} className="settings-card">
      <nav className="s-nav" aria-label={t("Settings sections")}>
        {account ? (
          <div className="s-user"><span className="avatar">{(account.name || account.email).slice(0, 1).toUpperCase()}</span>
            <div><b>{account.name || t("Your account")}</b><span>{account.email}</span></div></div>
        ) : (
          <div className="s-user"><span className="avatar dim"><Icon name="user" /></span>
            <div><b>{t("Not signed in")}</b></div></div>
        )}
        {links.map(([key, label, icon]) => (
          <button key={key} type="button" className="s-link" aria-current={section === key} onClick={() => { setSection(key); setNote(""); }}>
            <Icon name={icon} />{t(label)}</button>
        ))}
        {account && <button type="button" className="s-link danger" aria-current={section === "delete"} onClick={() => setSection("delete")}>
          <Icon name="trash" />{t("Delete account")}</button>}
      </nav>

      <div className="s-main">
        {section === "appearance" && <section>
          <h2>{t("Appearance")}</h2>
          <div className="themes" role="radiogroup" aria-label={t("Theme")}>
            {THEMES.map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={settings.theme === value} className="theme-card"
                onClick={() => change({ ...settings, theme: value })}>
                <span className={`theme-preview ${value}`}><i /><i /><b /></span>
                <span className="theme-name">{t(label)}<span className="radio-dot" /></span>
              </button>
            ))}
          </div>
          {languageOptionShown() && <>
            <h3 className="s-subhead">{t("Language")}</h3>
            <div className="lang-choice" role="radiogroup" aria-label={t("Language")}>
              {([["en", "English"], ["hi", "हिन्दी"]] as const).map(([value, label]) => (
                <button key={value} type="button" role="radio" lang={value} aria-checked={settings.language === value} className="btn-glass"
                  onClick={() => change({ ...settings, language: value })}>{label}</button>
              ))}
            </div>
          </>}
          {saved && <p className="saved"><Icon name="check" />{t("Saved")}</p>}
        </section>}

        {section === "browsing" && <section>
          <h2>{t("Opening sites")}</h2>
          <div className="s-row">
            <div><b>{t("Open sites in this tab")}</b></div>
            <button type="button" role="switch" aria-checked={settings.same_tab} aria-label={t("Open sites in this tab")} className="toggle"
              onClick={() => change({ ...settings, same_tab: !settings.same_tab })} />
          </div>
          {saved && <p className="saved"><Icon name="check" />{t("Saved")}</p>}
        </section>}

        {section === "account" && account && <section>
          <h2>{t("Account")}</h2>
          <form className="s-row name-row" onSubmit={saveName}>
            <div className="gfield">
              <label htmlFor="settings-name">{t("Name")}</label>
              <div className="gcontrol"><Icon name="user" />
                <input id="settings-name" type="text" autoComplete="name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
              </div>
            </div>
            <button type="submit" className="btn-glass" disabled={name.trim() === account.name}>{t("Save")}</button>
          </form>
          <div className="s-row">
            <div><b>{account.email}</b><span className="method">
              {account.google && <GoogleLogo />}
              {t(account.google && account.has_password ? "Google and password" : account.google ? "Google" : "Email and password")}
            </span></div>
            <span className="tag good">{t("CONFIRMED")}</span>
          </div>
          {account.has_password && <div className="s-row">
            <div><b>{t("Password")}</b></div>
            <button type="button" className="btn-glass" onClick={sendReset}>{t("Send reset link")}</button>
          </div>}
          <div className="s-row">
            <div><b>{t("Sign out")}</b></div>
            <button type="button" className="btn-glass" onClick={signOut}>{t("Sign out")}</button>
          </div>
          {note && <p className="s-note" role="status">{note}</p>}
        </section>}

        {section === "data" && account && <section>
          <h2>{t("Your data")}</h2>
          <div className="s-row">
            <div><b>{t("Scan history")}</b></div>
            <button type="button" className="btn-glass" onClick={clear}>{t("Clear history")}</button>
          </div>
          {note && <p className="s-note" role="status">{note}</p>}
        </section>}

        {section === "delete" && account && <section>
          <h2>{t("Delete account")}</h2>
          <p className="s-lede">{t("This can't be undone.")}</p>
          <form className="danger-zone" onSubmit={remove} noValidate>
            <b>{t("Deleting removes your email, settings and scan history for good.")}</b>
            <p>{t("Reports you sent stay, without your account on them.")}</p>
            <div className="gfield">
              <label htmlFor="delete-confirm">{t(password ? "Type your password to confirm" : "Type your email address to confirm")}</label>
              <div className="gcontrol"><Icon name={password ? "lock" : "mail"} />
                <input id="delete-confirm" type={password ? "password" : "email"} autoComplete={password ? "current-password" : "off"}
                  maxLength={254} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
              </div>
            </div>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="btn-danger-solid" type="submit" disabled={!confirmText}>{t("Delete my account")}</button>
          </form>
        </section>}

      </div>
    </GlassDialog>
  );
}
