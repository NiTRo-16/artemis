// Log in, sign up, forgot password, and finishing the links sent by email (confirm, reset).
import { useEffect, useState, type FormEvent } from "react";
import { useAccount, type AuthMode } from "../account";
import * as backend from "../api";
import { GlassDialog, GoogleLogo, Icon, Logo } from "./ui";

const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$/;

const MODES: Record<AuthMode, { title: string; intro: string; submit: string; email: boolean; password: string | null; autocomplete?: string }> = {
  signup: { title: "Create your account", intro: "It takes a minute. We'll email you a link to confirm.", submit: "Create account",
            email: true, password: "Password", autocomplete: "new-password" },
  login: { title: "Welcome back", intro: "Log in to see your history and settings.", submit: "Log in", email: true,
           password: "Password", autocomplete: "current-password" },
  forgot: { title: "Reset your password", intro: "Enter your account's email and we'll send you a link to choose a new password. It works for an hour.",
            submit: "Send reset link", email: true, password: null },
  verify: { title: "Confirm your email", intro: "Enter the password you chose when you signed up to finish creating your account.",
            submit: "Confirm email", email: false, password: "Password", autocomplete: "current-password" },
  reset: { title: "Choose a new password", intro: "Setting a new password signs you out on all your other devices.",
           submit: "Set password", email: false, password: "New password", autocomplete: "new-password" },
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
  const [email, setEmail] = useState("");
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

  useEffect(() => { setError(auth?.error ?? ""); setSent(null); setPassword(""); setPeek(false); }, [auth]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if ((m.email && !email.trim()) || (m.password && !password)) {
      setError(m.email && m.password ? "Enter your email and password." : m.email ? "Enter your email." : "Enter your password.");
      return;
    }
    if ((mode === "signup" || mode === "reset") && password.length < 10) {
      setError("Use a password of at least 10 characters.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const address = email.trim();
      if (mode === "signup") {
        await backend.signup(address, password);
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
    <GlassDialog open={!!auth} onClose={closeAuth} label={sent ? "Check your inbox" : m.title} className="auth-card">
      <aside className="auth-side">
        <div className="logo"><Logo />Artemis</div>
        <h2>{mode === "login" ? "Good to see you again." : "Keep every check in one place."}</h2>
        <p>Artemis works without an account. Signing in adds a few things that make it easier to come back to.</p>
        <ul className="perks">
          <li><span className="perk-icon"><Icon name="history" /></span><div><b>Your scan history</b><span>Your last 200 checks, ready to open again.</span></div></li>
          <li><span className="perk-icon"><Icon name="sync" /></span><div><b>Settings on every device</b><span>Theme and how sites open, wherever you sign in.</span></div></li>
          <li><span className="perk-icon"><Icon name="speed" /></span><div><b>More checks a minute</b><span>30 instead of 10.</span></div></li>
        </ul>
        <p className="side-foot">NO ADS · NO TRACKERS · DELETE ANY TIME</p>
      </aside>

      <div className="auth-main">
        {sent ? (
          <div className="sent-view" role="status">
            <div className="mail-badge"><Icon name="mail" /></div>
            <h1 className="auth-title">Check your inbox</h1>
            <p className="auth-intro">{sent.kind === "signup" ? "We sent a link to" : "If there's an account for this address, we sent a reset link to"}</p>
            <span className="email-chip">{sent.to}</span>
            <ol className="steps">
              {sent.kind === "signup" ? <>
                <li>Open the email from Artemis. It can take a minute to arrive.</li>
                <li>Click the link. It works once and expires in 24 hours.</li>
                <li>Enter the password you just chose, and you're in.</li>
              </> : <>
                <li>Open the email from Artemis. It can take a minute to arrive.</li>
                <li>Click the link. It works once and expires in 1 hour.</li>
                <li>Choose a new password. You'll be signed out everywhere else.</li>
              </>}
            </ol>
            <div className="sent-actions">
              {webmail && <a className="btn-glass" href={webmail} target="_blank" rel="noopener noreferrer">Open your inbox</a>}
              <button className="btn-glass" type="button" onClick={() => { setSent(null); openAuth(sent.kind === "signup" ? "signup" : "forgot"); }}>
                Use a different email</button>
            </div>
            <p className="fine">Not there? Check your spam folder.</p>
          </div>
        ) : (
          <>
            {tabs ? (
              <div className={`slide-tabs${mode === "login" ? " right" : ""}`} role="tablist">
                <span className="slide-thumb" />
                <button type="button" role="tab" aria-selected={mode === "signup"} onClick={() => openAuth("signup")}>Sign up</button>
                <button type="button" role="tab" aria-selected={mode === "login"} onClick={() => openAuth("login")}>Log in</button>
              </div>
            ) : mode === "forgot" ? (
              <button className="back-link" type="button" onClick={() => openAuth("login")}><Icon name="back" />Back to log in</button>
            ) : null}
            <h1 className="auth-title">{m.title}</h1>
            <p className="auth-intro">{m.intro}</p>

            {google && <>
              <a className="google-btn" href="/api/auth/google"><GoogleLogo />Continue with Google</a>
              <div className="or-line">or with your email</div>
            </>}

            <form onSubmit={submit} noValidate>
              {m.email && (
                <div className="gfield">
                  <label htmlFor="auth-email">Email</label>
                  <div className={`gcontrol${email && emailOk ? " ok" : ""}`}>
                    <Icon name="mail" />
                    <input id="auth-email" type="email" autoComplete="email" maxLength={254} value={email} placeholder="you@example.com"
                      onChange={(e) => setEmail(e.target.value)} autoFocus />
                    {email && emailOk && <Icon name="check" className="icon good" />}
                  </div>
                </div>
              )}
              {m.password && (
                <div className="gfield">
                  <div className="gfield-head">
                    <label htmlFor="auth-password">{m.password}</label>
                    {mode === "login" && <button type="button" className="text-link" onClick={() => openAuth("forgot")}>Forgot password?</button>}
                  </div>
                  <div className="gcontrol">
                    <Icon name="lock" />
                    <input id="auth-password" type={peek ? "text" : "password"} autoComplete={m.autocomplete} maxLength={128} value={password}
                      onChange={(e) => setPassword(e.target.value)} autoFocus={!m.email} />
                    <button className="peek" type="button" onClick={() => setPeek(!peek)} aria-pressed={peek}>{peek ? "Hide" : "Show"}</button>
                  </div>
                  {(mode === "signup" || mode === "reset") && <>
                    <div className="meter" aria-hidden="true">{[1, 2, 3, 4].map((n) => <i key={n} className={strength >= n ? (strength < 2 ? "weak" : "on") : ""} />)}</div>
                    <p className={`hint${password.length >= 10 ? " good" : ""}`}>
                      {password.length >= 10 && <Icon name="check" className="icon good" />}
                      At least 10 characters. A few unrelated words make a strong one.
                    </p>
                  </>}
                </div>
              )}
              {error && <p className="form-error" role="alert">{error}</p>}
              <button className="btn-solid" type="submit" disabled={busy}>{busy ? "One moment" : m.submit}</button>
              {(mode === "signup" || google) && (
                <p className="fine">
                  By {google ? "creating an account or continuing with Google" : "creating an account"}, you agree to
                  the <a href="/terms" target="_blank" rel="noopener">Terms</a> and <a href="/privacy" target="_blank" rel="noopener">Privacy policy</a>.
                  Artemis gives guidance, not a guarantee.
                </p>
              )}
              {mode === "forgot" && <p className="fine">Signed up with Google? You don't need a password: use Continue with Google instead.</p>}
              {tabs && (
                <p className="switch-line">
                  {mode === "signup" ? <>Already have an account? <button type="button" onClick={() => openAuth("login")}>Log in</button></>
                    : <>New to Artemis? <button type="button" onClick={() => openAuth("signup")}>Create an account</button></>}
                </p>
              )}
            </form>
          </>
        )}
      </div>
    </GlassDialog>
  );
}
