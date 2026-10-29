// Small building blocks shared by the pages.
import { useEffect, useRef, type ReactNode } from "react";

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
};

export function Icon({ name, className = "icon" }: { name: keyof typeof ICONS | string; className?: string }) {
  return <svg className={className} viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>;
}

/** A modal built on <dialog>: closes on Escape, on the backdrop and on the Close button. */
export function Dialog({ open, onClose, title, children, wide = false }:
  { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`dialog${wide ? " wide" : ""}`} aria-label={title} onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {open && <div className="dialog-body">
        <div className="dialog-head">
          <h2>{title}</h2>
          <button className="icon-btn" type="button" aria-label="Close" onClick={onClose}><Icon name="x" /></button>
        </div>
        {children}
      </div>}
    </dialog>
  );
}

const STATUS_WORD: Record<string, string> = { ok: "PASS", warn: "WARN", bad: "FLAG", done: "DONE", skipped: "SKIP", run: "RUN" };

export function StatusTag({ status }: { status?: string }) {
  return <span className={`status ${status ?? ""}`}>{status ? STATUS_WORD[status] ?? status.toUpperCase() : "· · ·"}</span>;
}

/** The risk ring from the portfolio's analyzer: fills to the score, coloured by risk level. */
export function RiskRing({ score, tone, scanning, label = "RISK" }:
  { score: number | null; tone: string; scanning?: boolean; label?: string }) {
  const filled = score == null ? 0 : (465 * Math.max(0, Math.min(100, score))) / 100;
  return (
    <div className={`ring ${tone}`}>
      <svg viewBox="0 0 170 170" aria-hidden="true">
        <circle className="ring-track" cx="85" cy="85" r="74" />
        {score != null && <circle className="ring-fill" cx="85" cy="85" r="74" strokeDasharray={`${filled} 465`} />}
        {scanning && <g className="ring-sweep"><path d="M85 85 L85 11" /></g>}
      </svg>
      <div className="ring-num">
        <b>{score ?? (scanning ? "" : "0")}</b>
        <span>{label}</span>
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
