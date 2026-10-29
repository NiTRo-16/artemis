// Home: the scan box, and a live panel that fills in as each check finishes.
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { startScan } from "../api";
import { Icon, RiskRing, StatusTag } from "../components/ui";
import { matchingRecent, rememberSearch, saveRecent } from "../recent";
import { riskTone } from "../report";
import type { Report, ScanEvent, StepStatus } from "../types";

export const STEPS: [string, string, string][] = [
  ["resolve", "Address", "DNS"],
  ["certificate", "Certificate", "TLS"],
  ["email", "Email records", "SPF, DMARC"],
  ["records", "Domain age and blocklists", "RDAP, CT, lists"],
  ["page", "Page in a sealed browser", "Chromium"],
  ["impersonation", "Lookalike and brand check", "incl. ML"],
];

type Live = { target: string; id: string | null; steps: Record<string, StepStatus>; report: Report | null; error: string };

export function ScanPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [target, setTarget] = useState("");
  const [live, setLive] = useState<Live | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<string[]>([]);
  const [active, setActive] = useState(-1);
  const source = useRef<EventSource | null>(null);

  useEffect(() => () => source.current?.close(), []);

  async function run(raw: string) {
    const value = raw.trim();
    if (!value) return;
    setRecent([]);
    setError("");
    setBusy(true);
    source.current?.close();
    setLive({ target: value, id: null, steps: {}, report: null, error: "" });
    try {
      const started = await startScan(value);
      rememberSearch(value);
      if (started.id === null) {   // a UPI link is answered straight away
        setLive({ target: value, id: null, steps: {}, report: started.report, error: "" });
        setBusy(false);
        return;
      }
      const id = started.id;
      setLive((l) => l && { ...l, id });
      const events = new EventSource(`/api/scans/${encodeURIComponent(id)}/events`);
      source.current = events;
      events.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as ScanEvent;
        if (event.type === "step") {
          setLive((l) => l && { ...l, steps: { ...l.steps, [event.step]: event.status } });
        } else {
          events.close();
          setBusy(false);
          setLive((l) => l && (event.type === "done" ? { ...l, report: event.report } : { ...l, error: event.message }));
        }
      };
      events.onerror = () => {
        events.close();
        setBusy(false);
        setLive((l) => l && !l.report ? { ...l, error: "Lost the connection to the scan. Try again." } : l);
      };
    } catch (err) {
      setBusy(false);
      setLive(null);
      setError((err as Error).message);
    }
  }

  // /?scan=example.com starts a scan straight away (the browser extension's "Full report" link).
  useEffect(() => {
    const requested = params.get("scan");
    if (requested) {
      setTarget(requested.slice(0, 2048));
      setParams({}, { replace: true });
      void run(requested.slice(0, 2048));
    }
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  function submit(event: FormEvent) {
    event.preventDefault();
    void run(target);
  }

  function pick(value: string) {
    setTarget(value);
    void run(value);
  }

  function onKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const items = recent.length ? recent : matchingRecent(target);
      if (!recent.length) setRecent(items);
      if (!items.length) return;
      setActive((a) => a < 0 ? (event.key === "ArrowDown" ? 0 : items.length - 1)
        : (a + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length);
    } else if (event.key === "Enter" && recent.length && active >= 0) {
      event.preventDefault();
      pick(recent[active]);
    } else if (event.key === "Escape") {
      setRecent([]);
    }
  }

  const report = live?.report ?? null;
  const done = STEPS.filter(([key]) => live?.steps[key]).length;
  const score = report ? report.risk?.score ?? null : null;

  return (
    <section className="hero">
      <div>
        <p className="eyebrow">Website, link and UPI safety check</p>
        <h1>Check a link before you trust it. <span className="soft">See the proof.</span></h1>
        <p className="lede">Paste a website, a link from a message, or a UPI payment link. Artemis checks its certificate,
          its age, whether it copies a known brand, and opens it in a sealed browser to look for fake login and payment forms.</p>
        <form className="scanbox" onSubmit={submit} role="search">
          <div className="field-row">
            <Icon name="link" className="icon dim" />
            <input aria-label="Domain, link or UPI ID to scan" placeholder="example.com, a link or a UPI ID" autoComplete="off"
              role="combobox" aria-expanded={recent.length > 0} aria-controls="recent-list"
              aria-activedescendant={active >= 0 ? `recent-${active}` : undefined}
              value={target} maxLength={2048}
              onChange={(e) => { setTarget(e.target.value); setActive(-1); setRecent(busy ? [] : matchingRecent(e.target.value)); }}
              onFocus={() => !busy && setRecent(matchingRecent(target))}
              onBlur={() => { setRecent([]); setActive(-1); }}
              onKeyDown={onKey} />
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Scanning" : "Scan"}</button>
          </div>
          {recent.length > 0 && (
            <div className="recent">
              <div className="recent-head"><span className="eyebrow">Recent</span>
                <button type="button" className="link-btn" onMouseDown={(e) => e.preventDefault()}
                  onClick={() => { saveRecent([]); setRecent([]); }}>Clear</button></div>
              <ul id="recent-list" role="listbox">
                {recent.map((r, i) => (
                  <li key={r} id={`recent-${i}`} role="option" aria-selected={i === active}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => pick(r)}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
        </form>
        <div className="accepts">
          <div className="accept"><Icon name="link" /><b>Websites</b><span>Domains and full links</span></div>
          <div className="accept"><Icon name="upi" /><b>UPI links</b><span>Payee, note and amount</span></div>
          <div className="accept"><Icon name="msg" /><b>Messages</b><span>Coming soon</span></div>
          <div className="accept"><Icon name="qr" /><b>QR codes</b><span>Coming soon</span></div>
        </div>
      </div>

      <div className="panel" aria-live="polite">
        <div className="panel-head"><span className="eyebrow">Live scan</span>
          <span className="eyebrow">{!live ? "Ready" : busy ? `${done} of ${STEPS.length}` : report ? "Finished" : "Stopped"}</span></div>
        <div className="target"><Icon name="link" className="icon dim" /><span>{live?.target || "Nothing scanned yet"}</span></div>
        {report?.kind === "upi" ? (
          <p className="note">{report.payment?.summary}</p>
        ) : (
          <div className="gauge-row">
            <ul className="checks">
              {STEPS.map(([key, label, where]) => (
                <li key={key}><span>{label}<span className="where">{where}</span></span>
                  <StatusTag status={live?.steps[key] ?? (busy ? "run" : undefined)} /></li>
              ))}
            </ul>
            <RiskRing score={score} tone={report ? riskTone(report) : "none"} scanning={busy}
              label={report && report.risk?.score == null ? "OFFLINE" : "RISK"} />
          </div>
        )}
        <div className="panel-foot">
          <span className="small">{live?.error || (report ? summary(report) : busy ? "Each check appears as it finishes." : "Results appear here as each check finishes.")}</span>
          {report && (
            <button className="btn" type="button"
              onClick={() => navigate(live?.id ? `/scan/${live.id}` : "/scan/upi", { state: { report, target: live?.target } })}>
              Open full report
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

function summary(report: Report): string {
  if (report.kind === "upi") return report.payment?.verdict ?? "";
  if (report.visit?.allowed) return "No problems found. The full report has the details.";
  return `${report.risk?.label ?? "Unknown"} risk. See the full report before you visit.`;
}
