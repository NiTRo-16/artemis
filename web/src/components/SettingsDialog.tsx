// Settings: theme and how sites open for everyone; account, data and deletion when signed in.
import { useEffect, useState, type FormEvent } from "react";
import { useAccount } from "../account";
import * as backend from "../api";
import type { Settings } from "../types";
import { GlassDialog, GoogleLogo, Icon } from "./ui";

type Section = "appearance" | "browsing" | "account" | "data" | "delete";

const THEMES: [Settings["theme"], string][] = [["system", "Match device"], ["light", "Light"], ["dark", "Dark"]];

export function SettingsDialog() {
  const { settingsOpen, setSettingsOpen, settings, saveSettings, account, setAccount, openAuth } = useAccount();
  const [section, setSection] = useState<Section>("appearance");
  const [saved, setSaved] = useState(false);
  const [note, setNote] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!settingsOpen) { setSection("appearance"); setNote(""); setConfirmText(""); setError(""); setSaved(false); }
  }, [settingsOpen]);
  useEffect(() => { if (!account && ["account", "data", "delete"].includes(section)) setSection("appearance"); }, [account, section]);

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
      setNote(`We sent a link to ${account.email}. It works for an hour.`);
    } catch (err) {
      setNote((err as Error).message);
    }
  }

  async function clear() {
    if (!window.confirm("Delete your whole scan history?")) return;
    try { await backend.clearHistory(); setNote("Your scan history was deleted."); }
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
  const links: [Section, string, string][] = [["appearance", "Appearance", "sun"], ["browsing", "Opening sites", "globe"],
    ...(account ? [["account", "Account", "user"], ["data", "Your data", "shield"]] as [Section, string, string][] : [])];

  return (
    <GlassDialog open={settingsOpen} onClose={close} label="Settings" className="settings-card">
      <nav className="s-nav" aria-label="Settings sections">
        {account ? (
          <div className="s-user"><span className="avatar">{account.email.slice(0, 1).toUpperCase()}</span>
            <div><b>Your account</b><span>{account.email}</span></div></div>
        ) : (
          <div className="s-user"><span className="avatar dim"><Icon name="user" /></span>
            <div><b>Not signed in</b><span>Saved in this browser</span></div></div>
        )}
        {links.map(([key, label, icon]) => (
          <button key={key} type="button" className="s-link" aria-current={section === key} onClick={() => { setSection(key); setNote(""); }}>
            <Icon name={icon} />{label}</button>
        ))}
        {account && <button type="button" className="s-link danger" aria-current={section === "delete"} onClick={() => setSection("delete")}>
          <Icon name="trash" />Delete account</button>}
      </nav>

      <div className="s-main">
        {section === "appearance" && <section>
          <h2>Appearance</h2>
          <p className="s-lede">{account ? "Saved to your account, so it follows you to every device." : "Saved in this browser."}</p>
          <h3 className="s-group">Theme</h3>
          <div className="themes" role="radiogroup" aria-label="Theme">
            {THEMES.map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={settings.theme === value} className="theme-card"
                onClick={() => change({ ...settings, theme: value })}>
                <span className={`theme-preview ${value}`}><i /><i /><b /></span>
                <span className="theme-name">{label}<span className="radio-dot" /></span>
              </button>
            ))}
          </div>
          {saved && <p className="saved"><Icon name="check" />Saved</p>}
        </section>}

        {section === "browsing" && <section>
          <h2>Opening sites</h2>
          <p className="s-lede">What happens when you choose to visit a site you've checked.</p>
          <div className="s-row">
            <div><b>Open sites in this tab</b><span>{settings.same_tab ? "On: sites open in this tab." : "Off: sites open in a new tab, so your result stays open."}</span></div>
            <button type="button" role="switch" aria-checked={settings.same_tab} aria-label="Open sites in this tab" className="toggle"
              onClick={() => change({ ...settings, same_tab: !settings.same_tab })} />
          </div>
          <div className="s-row">
            <div><b>Warn before risky sites</b><span>Artemis always asks once more before you open a site with high-risk signs.</span></div>
            <span className="tag good">ALWAYS ON</span>
          </div>
          {saved && <p className="saved"><Icon name="check" />Saved</p>}
        </section>}

        {section === "account" && account && <section>
          <h2>Account</h2>
          <p className="s-lede">How you sign in to Artemis.</p>
          <h3 className="s-group">Signed in as</h3>
          <div className="s-row">
            <div><b>{account.email}</b><span className="method">
              {account.google && <GoogleLogo />}
              {account.google && account.has_password ? "Google and password" : account.google ? "Google" : "Email and password"}
            </span></div>
            <span className="tag good">CONFIRMED</span>
          </div>
          {account.has_password && <div className="s-row">
            <div><b>Password</b><span>Change it with a reset link sent to your email.</span></div>
            <button type="button" className="btn-glass" onClick={sendReset}>Send reset link</button>
          </div>}
          <div className="s-row">
            <div><b>Sign out</b><span>Signs you out on this device.</span></div>
            <button type="button" className="btn-glass" onClick={signOut}>Sign out</button>
          </div>
          {note && <p className="s-note" role="status">{note}</p>}
        </section>}

        {section === "data" && account && <section>
          <h2>Your data</h2>
          <p className="s-lede">What Artemis keeps for your account, and how to remove it.</p>
          <div className="s-row">
            <div><b>Scan history</b><span>Your most recent 200 checks. Only you can see them.</span></div>
            <button type="button" className="btn-glass" onClick={clear}>Clear history</button>
          </div>
          <div className="s-row">
            <div><b>Shared results</b><span>A result you share stays available for 30 days to anyone with the link, then it's deleted.</span></div>
          </div>
          <div className="s-row">
            <div><b>Privacy policy</b><span>Everything Artemis collects, why, and for how long.</span></div>
            <a className="btn-glass" href="/privacy" target="_blank" rel="noopener">Read it</a>
          </div>
          {note && <p className="s-note" role="status">{note}</p>}
        </section>}

        {section === "delete" && account && <section>
          <h2>Delete account</h2>
          <p className="s-lede">This can't be undone.</p>
          <form className="danger-zone" onSubmit={remove} noValidate>
            <b>Deleting removes your email, settings and scan history for good.</b>
            <p>Reports you sent stay, without your account on them. You can always use Artemis without an account.</p>
            <div className="gfield">
              <label htmlFor="delete-confirm">{password ? "Type your password to confirm" : "Type your email address to confirm"}</label>
              <div className="gcontrol"><Icon name={password ? "lock" : "mail"} />
                <input id="delete-confirm" type={password ? "password" : "email"} autoComplete={password ? "current-password" : "off"}
                  maxLength={254} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
              </div>
            </div>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="btn-danger-solid" type="submit" disabled={!confirmText}>Delete my account</button>
          </form>
        </section>}

        {!account && (section === "appearance" || section === "browsing") && (
          <div className="s-invite">
            <div><b>Keep these on every device</b><span>Sign in and your settings and scan history follow you.</span></div>
            <button type="button" className="btn-glass" onClick={() => { close(); openAuth("login"); }}>Log in</button>
          </div>
        )}
      </div>
    </GlassDialog>
  );
}
