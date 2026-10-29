// Log in, sign up, forgot password, and finishing the links sent by email (confirm, reset).
import { useEffect, useState, type FormEvent } from "react";
import { useAccount, type AuthMode } from "../account";
import * as backend from "../api";
import { Dialog, GoogleLogo } from "./ui";

const OPTIONAL_NOTE = "An account is optional. It keeps your scan history, saves your settings across devices, and raises your limit from 10 to 30 scans a minute.";

const MODES: Record<AuthMode, { title: string; intro: string; submit: string; email: boolean; password: string | null; autocomplete?: string }> = {
  signup: { title: "Create your account", intro: OPTIONAL_NOTE, submit: "Create account", email: true,
            password: "Password (at least 10 characters)", autocomplete: "new-password" },
  login: { title: "Welcome back", intro: OPTIONAL_NOTE, submit: "Log in", email: true, password: "Password",
           autocomplete: "current-password" },
  forgot: { title: "Reset your password", intro: "Enter your account's email and we'll send you a link to choose a new password.",
            submit: "Send reset link", email: true, password: null },
  verify: { title: "Confirm your email", intro: "Enter the password you chose when you signed up to finish creating your account.",
            submit: "Confirm email", email: false, password: "Password", autocomplete: "current-password" },
  reset: { title: "Choose a new password", intro: "Setting a new password signs you out on all your other devices.",
           submit: "Set password", email: false, password: "New password (at least 10 characters)", autocomplete: "new-password" },
};

export function AuthDialog() {
  const { auth, openAuth, closeAuth, googleSignin, setAccount, applySettings, saveSettings, settings } = useAccount();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState("");
  const [busy, setBusy] = useState(false);
  const mode = auth?.mode ?? "signup";
  const m = MODES[mode];
  const google = googleSignin && (mode === "signup" || mode === "login");

  useEffect(() => { setError(auth?.error ?? ""); setSent(""); setPassword(""); }, [auth]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if ((m.email && !email.trim()) || (m.password && !password)) {
      setError(m.email && m.password ? "Enter your email and password." : m.email ? "Enter your email." : "Enter your password.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const address = email.trim();
      if (mode === "signup") {
        await backend.signup(address, password);
        setSent(`We sent a link to ${address}. Open it to finish creating your account. It expires in 24 hours; if it doesn't arrive, check your spam folder.`);
      } else if (mode === "forgot") {
        await backend.forgotPassword(address);
        setSent(`If there's an account for ${address}, we've sent it a link to choose a new password. The link expires in 1 hour.`);
      } else {
        const account = mode === "login" ? await backend.login(address, password)
          : mode === "verify" ? await backend.verifyEmail(auth!.token, password)
          : await backend.resetPassword(auth!.token, password);
        setAccount(account);
        if (mode === "verify") await saveSettings(settings);   // a new account keeps choices made before it existed
        else applySettings(account.settings);                  // an existing account's settings win
        closeAuth();
      }
      setPassword("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={!!auth} onClose={closeAuth} title={sent ? "Check your inbox" : m.title}>
      {sent ? (
        <div role="status">
          <p className="note">{sent}</p>
          <div className="actions"><button className="btn" type="button" onClick={closeAuth}>Done</button></div>
        </div>
      ) : (
        <>
          <p className="note">{m.intro}</p>
          {(mode === "signup" || mode === "login") && (
            <div className="seg tabs" role="tablist">
              <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => openAuth("signup")}>Sign up</button>
              <button type="button" role="tab" aria-selected={mode === "login"} onClick={() => openAuth("login")}>Log in</button>
            </div>
          )}
          {google && (
            <>
              <a className="google" href="/api/auth/google"><GoogleLogo />Continue with Google</a>
              <div className="or">OR USE YOUR EMAIL</div>
            </>
          )}
          <form onSubmit={submit} noValidate>
            {m.email && (
              <label className="field">Email
                <input className="input" type="email" autoComplete="email" maxLength={254} value={email}
                  onChange={(e) => setEmail(e.target.value)} autoFocus />
              </label>
            )}
            {m.password && (
              <label className="field">{m.password}
                <input className="input" type="password" autoComplete={m.autocomplete} maxLength={128} value={password}
                  onChange={(e) => setPassword(e.target.value)} autoFocus={!m.email} />
              </label>
            )}
            {error && <p className="form-error" role="alert">{error}</p>}
            {(mode === "signup" || google) && (
              <p className="note small">
                {google ? "By creating an account or continuing with Google" : "By creating an account"}, you agree to
                the <a href="/terms" target="_blank" rel="noopener">Terms and conditions</a> and <a href="/privacy" target="_blank" rel="noopener">Privacy policy</a>.
                Artemis gives guidance, not a guarantee.
              </p>
            )}
            <div className="actions">
              <button className="btn btn-primary btn-wide" type="submit" disabled={busy}>{m.submit}</button>
              {mode === "login" && <button className="btn btn-ghost" type="button" onClick={() => openAuth("forgot")}>Forgot password?</button>}
            </div>
          </form>
        </>
      )}
    </Dialog>
  );
}
