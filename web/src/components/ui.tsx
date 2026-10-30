// Small building blocks shared by the pages.
import { useEffect, useRef, type ReactNode } from "react";
import { tk, useT } from "../i18n";

/** Text where `backticks` mark code, as the scanner writes finding titles and fixes. */
export function Rich({ text }: { text: string }) {
  return <>{text.split("`").map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part))}</>;
}

const ICONS: Record<string, ReactNode> = {
  scan: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /><path d="M12 4v3M12 17v3M4 12h3M17 12h3" /></>,
  msg: <><path d="M4 5h16v11H9l-5 4z" /><path d="M8 9h8M8 12h5" /></>,
  qr: <><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4z" /><path d="M14 14h2v2h-2zM18 14h2M14 18h2M18 18h2v2" /></>,
  watch: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z" /><circle cx="12" cy="12" r="2.5" /></>,
  history: <><path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5" /><path d="M4 4v4.5h4.5M12 8v4l3 2" /></>,
  code: <path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14" />,
  link: <><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>,
  upi: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M3 10h18M7 15h4" /></>,
  menu: <path d="M4 8h16M4 16h16" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  share: <><path d="M8 12h8M13 7l5 5-5 5" /><path d="M4 5v14" /></>,
  flag: <path d="M5 21V4M5 4h11l-2 4 2 4H5" />,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></>,
  out: <path d="M9 6H5v13h13v-4M13 4h7v7M20 4l-9 9" />,
  mail: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3.5 7l8.5 6 8.5-6" /></>,
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  sync: <><path d="M20 12a8 8 0 0 1-14 5.3M4 12a8 8 0 0 1 14-5.3" /><path d="M18 3v4h-4M6 21v-4h4" /></>,
  speed: <><path d="M4 18a8 8 0 1 1 16 0" /><path d="M12 18l4-6" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  back: <path d="M15 6l-6 6 6 6" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  shield: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />,
  trash: <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />,
  signout: <path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" />,
};

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 26 26" aria-hidden="true">
      <circle cx="13" cy="13" r="11.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M13 13 L21.2 4.8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="13" cy="13" r="2.2" fill="var(--accent)" />
    </svg>
  );
}

export function Icon({ name, className = "icon" }: { name: keyof typeof ICONS | string; className?: string }) {
  return <svg className={className} viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>;
}

function useModal(open: boolean) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return ref;
}

/** A frosted-glass modal for the account screens, laid out by its children. Same closing rules as Dialog. */
export function GlassDialog({ open, onClose, label, className, children }:
  { open: boolean; onClose: () => void; label: string; className: string; children: ReactNode }) {
  const ref = useModal(open);
  const t = useT();
  return (
    <dialog ref={ref} className={`glass-dialog ${className}`} aria-label={label} onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {open && <>
        <button className="glass-close" type="button" aria-label={t("Close")} onClick={onClose}><Icon name="x" /></button>
        {children}
      </>}
    </dialog>
  );
}

/** A modal built on <dialog>: closes on Escape, on the backdrop and on the Close button. */
export function Dialog({ open, onClose, title, children, wide = false }:
  { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useModal(open);
  const t = useT();
  return (
    <dialog ref={ref} className={`dialog${wide ? " wide" : ""}`} aria-label={title} onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {open && <div className="dialog-body">
        <div className="dialog-head">
          <h2>{title}</h2>
          <button className="icon-btn" type="button" aria-label={t("Close")} onClick={onClose}><Icon name="x" /></button>
        </div>
        {children}
      </div>}
    </dialog>
  );
}

const STATUS_WORD: Record<string, string> = { ok: tk("PASS"), warn: tk("WARN"), bad: tk("FLAG"), done: tk("DONE"), skipped: tk("SKIP"), run: tk("RUN") };

export function StatusTag({ status }: { status?: string }) {
  const t = useT();
  return <span className={`status ${status ?? ""}`}>{status ? t(STATUS_WORD[status] ?? status.toUpperCase()) : "· · ·"}</span>;
}

const SAFETY: Record<string, [string, string]> = {
  danger: ["bad", tk("Unsafe")], caution: ["warn", tk("Be careful")], clear: ["ok", tk("No warning signs")],
};

/** A UPI result at a glance. Green never says "safe": Artemis can't see who owns a UPI ID. */
export function SafetyBanner({ level }: { level: string }) {
  const t = useT();
  const [tone, word] = SAFETY[level] ?? SAFETY.caution;
  return <p className={`safety-banner ${tone}`}><span className="dot" />{t(word)}</p>;
}

/** The risk ring from the portfolio's analyzer: fills to the score, coloured by risk level. */
export function RiskRing({ score, tone, scanning, label = "RISK" }:
  { score: number | null; tone: string; scanning?: boolean; label?: string }) {
  const t = useT();
  const filled = score == null ? 0 : (465 * Math.max(0, Math.min(100, score))) / 100;
  return (
    <div className={`ring ${tone}`}>
      <svg viewBox="0 0 170 170" aria-hidden="true">
        <circle className="ring-track" cx="85" cy="85" r="74" />
        {score != null && <circle className="ring-fill" cx="85" cy="85" r="74" strokeDasharray={`${filled} 465`} />}
        {scanning && <g className="ring-sweep"><path d="M85 85 L85 11" /></g>}
      </svg>
      <div className="ring-num">
        <b>{score ?? ""}</b>
        <span>{t(label)}</span>
      </div>
    </div>
  );
}

export function GoogleLogo() {
  // Google's "G", as its branding guidelines require on sign-in buttons.
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}
