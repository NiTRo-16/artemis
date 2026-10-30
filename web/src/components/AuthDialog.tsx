// Log in, sign up, forgot password, and finishing the links sent by email (confirm, reset).
import { useEffect, useState, type FormEvent } from "react";
import { useAccount, type AuthMode } from "../account";
import * as backend from "../api";
import { tk, useT, withSlots } from "../i18n";
import { GlassDialog, GoogleLogo, Icon, Logo } from "./ui";

const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$/;

const MODES: Record<AuthMode, { title: string; intro: string; submit: string; email: boolean; password: string | null; autocomplete?: string }> = {
  signup: { title: tk("Create your account"), intro: "", submit: tk("Create account"),
            email: true, password: tk("Password"), autocomplete: "new-password" },
  login: { title: tk("Welcome back"), intro: "", submit: tk("Log in"), email: true,
           password: tk("Password"), autocomplete: "current-password" },
  forgot: { title: tk("Reset your password"), intro: tk("We'll email you a link to choose a new password."),
            submit: tk("Send reset link"), email: true, password: null },
  verify: { title: tk("Confirm your email"), intro: tk("Enter the password you chose when you signed up."),
            submit: tk("Confirm email"), email: false, password: tk("Password"), autocomplete: "current-password" },
  reset: { title: tk("Choose a new password"), intro: tk("Setting a new password signs you out on all your other devices."),
           submit: tk("Set password"), email: false, password: tk("New password"), autocomplete: "new-password" },
};

/** 0 to 4 bars. Length matters most; mixing kinds of characters adds a little. Nothing is sent anywhere. */
export function passwordStrength(pw: string): number {
  if (!pw) return 0;
  if (pw.length < 10) return 1;
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((re) => re.test(pw)).length;
  return Math.min(4, 2 + (pw.length >= 14 ? 1 : 0) + (kinds >= 2 ? 1 : 0));
}

function webmailFor(email: string): string | null {
  const domain = email.split("@")[1]?.toLowerCase();
  return domain === "gmail.com" || domain === "googlemail.com" ? "https://mail.google.com/"
    : domain === "outlook.com" || domain === "hotmail.com" || domain === "live.com" ? "https://outlook.live.com/mail/"
    : domain === "yahoo.com" || domain === "yahoo.in" ? "https://mail.yahoo.com/" : null;
}

export function AuthDialog() {
  const { auth, openAuth, closeAuth, googleSignin, setAccount, applySettings, saveSettings, settings } = useAccount();
  const t = useT();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [peek, setPeek] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState<{ to: string; kind: "signup" | "forgot" } | null>(null);
  const [busy, setBusy] = useState(false);
  const mode = auth?.mode ?? "signup";
  const m = MODES[mode];
  const tabs = mode === "signup" || mode === "login";
  const google = googleSignin && tabs;
  const emailOk = EMAIL.test(email.trim());
  const strength = passwordStrength(password);

  useEffect(() => { setError(t(auth?.error ?? "")); setSent(null); setPassword(""); setPeek(false); }, [auth]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (mode === "signup" && !name.trim()) {
      setError(t("Enter your name."));
      return;
    }
    if ((m.email && !email.trim()) || (m.password && !password)) {
      setError(t(m.email && m.password ? "Enter your email and password." : m.email ? "Enter your email." : "Enter your password."));
      return;
    }
    if ((mode === "signup" || mode === "reset") && password.length < 10) {
      setError(t("Use a password of at least 10 characters."));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const address = email.trim();
      if (mode === "signup") {
        await backend.signup(address, password, name.trim());
        setSent({ to: address, kind: "signup" });
      } else if (mode === "forgot") {
        await backend.forgotPassword(address);
        setSent({ to: address, kind: "forgot" });
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

  const webmail = sent && webmailFor(sent.to);
  return (
    <GlassDialog open={!!auth} onClose={closeAuth} label={t(sent ? "Check your inbox" : m.title)} className="auth-card">
      <aside className="auth-side">
        <div className="logo"><Logo />Artemis</div>
        <h2>{t(mode === "login" ? "Good to see you again." : "Keep every check in one place.")}</h2>
        <ul className="perks">
          <li><span className="perk-icon"><Icon name="history" /></span><div><b>{t("Your scan history")}</b></div></li>
          <li><span className="perk-icon"><Icon name="sync" /></span><div><b>{t("Settings on every device")}</b></div></li>
          <li><span className="perk-icon"><Icon name="speed" /></span><div><b>{t("30 checks a minute")}</b><span>{t("Instead of 10")}</span></div></li>
        </ul>
      </aside>

      <div className="auth-main">
        {sent ? (
          <div className="sent-view" role="status">
            <div className="mail-badge"><Icon name="mail" /></div>
            <h1 className="auth-title">{t("Check your inbox")}</h1>
            <p className="auth-intro">{t(sent.kind === "signup" ? "We sent a link to" : "If there's an account for this address, we sent a reset link to")}</p>
            <span className="email-chip">{sent.to}</span>
            <p className="auth-intro">{t(sent.kind === "signup" ? "The link works for 24 hours." : "The link works for 1 hour.")}</p>
            <div className="sent-actions">
              {webmail && <a className="btn-glass" href={webmail} target="_blank" rel="noopener noreferrer">{t("Open your inbox")}</a>}
              <button className="btn-glass" type="button" onClick={() => { setSent(null); openAuth(sent.kind === "signup" ? "signup" : "forgot"); }}>
                {t("Use a different email")}</button>
            </div>
            <p className="fine">{t("Not there? Check your spam folder.")}</p>
          </div>
        ) : (
          <>
            {tabs ? (
              <div className={`slide-tabs${mode === "login" ? " right" : ""}`} role="tablist">
                <span className="slide-thumb" />
                <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => openAuth("signup")}>{t("Sign up")}</button>
                <button type="button" role="tab" aria-selected={mode === "login"} onClick={() => openAuth("login")}>{t("Log in")}</button>
              </div>
            ) : mode === "forgot" ? (
              <button className="back-link" type="button" onClick={() => openAuth("login")}><Icon name="back" />{t("Back to log in")}</button>
            ) : null}
            <h1 className="auth-title">{t(m.title)}</h1>
            {m.intro && <p className="auth-intro">{t(m.intro)}</p>}

            {google && <>
              <a className="google-btn" href="/api/auth/google"><GoogleLogo />{t("Continue with Google")}</a>
              <div className="or-line">{t("or")}</div>
            </>}

            <form onSubmit={submit} noValidate>
              {mode === "signup" && (
                <div className="gfield">
                  <label htmlFor="auth-name">{t("Name")}</label>
                  <div className="gcontrol">
                    <Icon name="user" />
                    <input id="auth-name" type="text" autoComplete="name" maxLength={80} value={name}
                      onChange={(e) => setName(e.target.value)} autoFocus />
                  </div>
                </div>
              )}
              {m.email && (
                <div className="gfield">
                  <label htmlFor="auth-email">{t("Email")}</label>
                  <div className={`gcontrol${email && emailOk ? " ok" : ""}`}>
                    <Icon name="mail" />
                    <input id="auth-email" type="email" autoComplete="email" maxLength={254} value={email} placeholder="you@example.com"
                      onChange={(e) => setEmail(e.target.value)} autoFocus={mode !== "signup"} />
                    {email && emailOk && <Icon name="check" className="icon good" />}
                  </div>
                </div>
              )}
              {m.password && (
                <div className="gfield">
                  <div className="gfield-head">
                    <label htmlFor="auth-password">{t(m.password)}</label>
                    {mode === "login" && <button type="button" className="text-link" onClick={() => openAuth("forgot")}>{t("Forgot password?")}</button>}
                  </div>
                  <div className="gcontrol">
                    <Icon name="lock" />
                    <input id="auth-password" type={peek ? "text" : "password"} autoComplete={m.autocomplete} maxLength={128} value={password}
                      onChange={(e) => setPassword(e.target.value)} autoFocus={!m.email} />
                    <button className="peek" type="button" onClick={() => setPeek(!peek)} aria-pressed={peek}>{t(peek ? "Hide" : "Show")}</button>
                  </div>
                  {(mode === "signup" || mode === "reset") && <>
                    <div className="meter" aria-hidden="true">{[1, 2, 3, 4].map((n) => <i key={n} className={strength >= n ? (strength < 2 ? "weak" : "on") : ""} />)}</div>
                    <p className={`hint${password.length >= 10 ? " good" : ""}`}>
                      {password.length >= 10 && <Icon name="check" className="icon good" />}
                      {t("At least 10 characters")}
                    </p>
                  </>}
                </div>
              )}
              {error && <p className="form-error" role="alert">{error}</p>}
              <button className="btn-solid" type="submit" disabled={busy}>{t(busy ? "One moment" : m.submit)}</button>
              {(mode === "signup" || google) && (
                <p className="fine">
                  {withSlots(t(google ? "By creating an account or continuing with Google, you agree to the {terms} and {privacy}."
                    : "By creating an account, you agree to the {terms} and {privacy}."), {
                    terms: <a key="terms" href="/terms" target="_blank" rel="noopener">{t("Terms")}</a>,
                    privacy: <a key="privacy" href="/privacy" target="_blank" rel="noopener">{t("Privacy policy")}</a>,
                  })}
                </p>
              )}
              {mode === "forgot" && <p className="fine">{t("Signed up with Google? You don't need a password: use Continue with Google instead.")}</p>}
            </form>
          </>
        )}
      </div>
    </GlassDialog>
  );
}
