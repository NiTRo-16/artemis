// The portfolio-style frame: header with the logo, then the tools, then account controls; and the footer.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Link, useLocation, useNavigate } from "react-router";
import { useAccount } from "../account";
import * as backend from "../api";
import { Icon } from "./ui";

export const TOOLS = [
  { to: "/", label: "Scan", icon: "scan", end: true },
  { to: "/messages", label: "Message check", icon: "msg", soon: true },
  { to: "/qr", label: "QR and UPI", icon: "qr", soon: true },
  { to: "/watch", label: "Domain watch", icon: "watch", soon: true },
  { to: "/history", label: "History", icon: "history" },
  { to: "/developers", label: "API", icon: "code", soon: true },
];

function Logo() {
  return (
    <svg className="logo-mark" viewBox="0 0 26 26" aria-hidden="true">
      <circle cx="13" cy="13" r="11.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M13 13 L21.2 4.8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="13" cy="13" r="2.2" fill="var(--accent)" />
    </svg>
  );
}

function ToolLinks({ onPick }: { onPick?: () => void }) {
  const { pathname } = useLocation();
  return (
    <>
      {TOOLS.map((t) => (
        <NavLink key={t.to} to={t.to} end={t.end} onClick={onPick}
          className={({ isActive }) => `tool${isActive || (t.to === "/" && pathname.startsWith("/scan/")) ? " active" : ""}`}>
          <Icon name={t.icon} />{t.label}{t.soon && <span className="soon">SOON</span>}
        </NavLink>
      ))}
    </>
  );
}

export function Frame({ children }: { children: ReactNode }) {
  const { account, openAuth, setSettingsOpen } = useAccount();
  const [menu, setMenu] = useState(false);
  return (
    <div className="frame">
      <header className="header">
        <Link className="logo" to="/" aria-label="Artemis home"><Logo />Artemis</Link>
        <nav className="tools" aria-label="Tools"><ToolLinks /></nav>
        <div className="account">
          <button className="icon-btn" type="button" aria-label="Settings" onClick={() => setSettingsOpen(true)}><Icon name="gear" /></button>
          {account ? (
            <AccountMenu />
          ) : (
            <>
              <button className="btn btn-ghost hide-small" type="button" onClick={() => openAuth("login")}>Log in</button>
              <button className="btn btn-primary" type="button" onClick={() => openAuth("signup")}>Sign up</button>
            </>
          )}
          <button className="icon-btn menu-btn" type="button" aria-label="Menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>
            <Icon name="menu" />
          </button>
        </div>
        {menu && (
          <nav className="sheet" aria-label="Tools">
            <ToolLinks onPick={() => setMenu(false)} />
            {!account && <button className="tool" type="button" onClick={() => { setMenu(false); openAuth("login"); }}>Log in</button>}
          </nav>
        )}
      </header>
      <main className="main">{children}</main>
      <footer className="footer">
        <span>Artemis</span>
        <nav><a href="/privacy">Privacy policy</a><a href="/terms">Terms and conditions</a></nav>
      </footer>
    </div>
  );
}

/** The signed-in chip in the header, and the menu it opens. */
function AccountMenu() {
  const { account, setAccount, setSettingsOpen } = useAccount();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);

  if (!account) return null;
  const initial = account.email.slice(0, 1).toUpperCase();
  async function signOut() {
    setOpen(false);
    try { await backend.logout(); } catch { /* signed out here regardless */ }
    setAccount(null);
  }
  return (
    <div className="account-menu" ref={box}>
      <button className="user-chip" type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="avatar">{initial}</span><span className="user-email">{account.email}</span>
      </button>
      {open && (
        <div className="menu-panel" role="menu">
          <div className="menu-head"><span className="avatar">{initial}</span><div><b>Signed in</b><span>{account.email}</span></div></div>
          <button className="menu-item" role="menuitem" type="button" onClick={() => { setOpen(false); navigate("/history"); }}>
            <Icon name="history" />Scan history</button>
          <button className="menu-item" role="menuitem" type="button" onClick={() => { setOpen(false); setSettingsOpen(true); }}>
            <Icon name="gear" />Settings</button>
          <div className="menu-sep" />
          <button className="menu-item" role="menuitem" type="button" onClick={signOut}><Icon name="signout" />Sign out</button>
        </div>
      )}
    </div>
  );
}
