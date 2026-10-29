// Theme, how sites open, and (when signed in) signing out and deleting the account.
import { useState, type FormEvent } from "react";
import { useAccount } from "../account";
import * as backend from "../api";
import { Dialog } from "./ui";

export function SettingsDialog() {
  const { settingsOpen, setSettingsOpen, settings, saveSettings, account, setAccount } = useAccount();
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const close = () => { setSettingsOpen(false); setConfirm(""); setError(""); };
  const password = !account || account.has_password !== false;   // accounts made with Google may have no password

  async function signOut() {
    try { await backend.logout(); } catch { /* signed out here regardless */ }
    setAccount(null);
    close();
  }

  async function remove(event: FormEvent) {
    event.preventDefault();
    try {
      await backend.deleteAccount(confirm);
      setAccount(null);
      close();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Dialog open={settingsOpen} onClose={close} title="Settings">
      <p className="note">{account ? `Saved to your account (${account.email}) and this browser.`
        : "Saved in this browser. Sign in to keep them on every device."}</p>
      <section className="dlg-section">
        <h3>Theme</h3>
        <div className="choices" role="radiogroup" aria-label="Theme">
          {([["system", "Match my device"], ["light", "Light"], ["dark", "Dark"]] as const).map(([value, label]) => (
            <label className="choice" key={value}>
              <input type="radio" name="theme" checked={settings.theme === value}
                onChange={() => saveSettings({ ...settings, theme: value })} /> {label}
            </label>
          ))}
        </div>
      </section>
      <section className="dlg-section">
        <h3>Opening sites</h3>
        <label className="choice">
          <input type="checkbox" checked={settings.same_tab}
            onChange={(e) => saveSettings({ ...settings, same_tab: e.target.checked })} /> Open sites in this tab instead of a new one
        </label>
      </section>
      {account && (
        <section className="dlg-section">
          <h3>Account</h3>
          <div className="actions"><button className="btn" type="button" onClick={signOut}>Sign out</button></div>
          <p className="note">Deleting your account removes your email, settings and scan history for good.</p>
          <form onSubmit={remove} noValidate>
            <label className="field">{password ? "Confirm with your password" : "Type your email address to confirm"}
              <input className="input" type={password ? "password" : "email"} autoComplete={password ? "current-password" : "off"}
                maxLength={254} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <div className="actions"><button className="btn btn-danger" type="submit">Delete account</button></div>
          </form>
        </section>
      )}
    </Dialog>
  );
}
