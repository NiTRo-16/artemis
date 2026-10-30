// The full result of a scan, at /scan/<id> (kept 24 hours) and, read-only, at /r/<id> when shared.
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useAccount } from "../account";
import { getScan, getShared, shareScan } from "../api";
import { ReportDialog, RiskDialog } from "../components/ReportDialogs";
import { Icon, Rich } from "../components/ui";
import { reportable, riskFactors, riskTone, safeUrl } from "../report";
import type { Finding, Impersonation, Payment, Report } from "../types";

export function ResultPage() {
  const { id = "" } = useParams();
  const state = useLocation().state as { report?: Report } | null;
  const [report, setReport] = useState<Report | null>(state?.report ?? null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (report || id === "upi") return;
    getScan(id).then((s) => s.report ? setReport(s.report) : setError(s.error || "This scan hasn't finished."))
      .catch((err) => setError((err as Error).message));
  }, [id, report]);

  if (!report) {
    return <Missing text={error || (id === "upi" ? "UPI checks aren't kept. Check the link again." : "Loading the result")} />;
  }
  return <ResultView report={report} shareId={id === "upi" ? null : id} />;
}

export function SharedPage() {
  const { id = "" } = useParams();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getShared(id).then(setReport).catch((err) => setError((err as Error).message)); }, [id]);
  if (!report) return <Missing text={error || "Loading the shared result"} />;
  return <ResultView report={report} shareId={null} shared />;
}

function Missing({ text }: { text: string }) {
  return (
    <div className="tool-head">
      <p className="eyebrow">Scan result</p>
      <h1 className="small-h1">{text}</h1>
      <Link className="btn btn-primary" to="/">Scan a site</Link>
    </div>
  );
}

export function ResultView({ report, shareId, shared = false }: { report: Report; shareId: string | null; shared?: boolean }) {
  const { settings } = useAccount();
  const [reporting, setReporting] = useState(false);
  const [warning, setWarning] = useState(false);
  const [shareText, setShareText] = useState("");
  const upi = report.kind === "upi";
  const tone = riskTone(report);
  const url = safeUrl(report.visit?.url);
  const factors = riskFactors(report);
  const categories = report.categories ?? [];
  const findings = report.findings ?? [];

  async function share() {
    if (!shareId) return;
    try {
      const { url: path } = await shareScan(shareId);
      const link = `${location.origin}${path}`;
      try { await navigator.clipboard.writeText(link); setShareText(`Link copied: ${link}`); }
      catch { setShareText(`Share this link: ${link}`); }
    } catch (err) {
      setShareText((err as Error).message);
    }
  }

  return (
    <article>
      <div className="result-head">
        <div>
          <p className="eyebrow">{shared ? "Shared scan result" : "Scan result"}</p>
          <h2 className="result-target">{report.domain}</h2>
          <div className="verdict-row">
            {report.risk && <span className={`verdict ${tone}`}><span className="dot" />{report.risk.label.toUpperCase()} RISK
              {report.risk.score != null && ` · ${report.risk.score}`}</span>}
            {!upi && report.resolves === false && <span className="verdict none"><span className="dot" />OFFLINE</span>}
            <span className="main-result">{upi ? report.payment?.verdict : report.impersonation?.verdict}</span>
          </div>
        </div>
        <div className="actions">
          {shareId && <button className="btn" type="button" onClick={share}><Icon name="share" />Share result</button>}
          {reportable(report) && <button className="btn" type="button" onClick={() => setReporting(true)}>
            <Icon name="flag" />{upi ? "Report this UPI ID" : "Report site"}</button>}
          {url && report.visit?.allowed && <a className="btn btn-primary" href={url} target={settings.same_tab ? "_self" : "_blank"}
            rel="noopener noreferrer">Continue to {report.domain}</a>}
          {url && !report.visit?.allowed && <button className="btn btn-danger" type="button" onClick={() => setWarning(true)}>Continue anyway</button>}
        </div>
      </div>
      {shareText && <p className="share-note" role="status">{shareText}</p>}

      <div className="grid-2">
        <div className="stack">
          <section className="card">
            <h3>{factors.length ? "Why it's risky" : "What we found"}</h3>
            {factors.length ? (
              <>
                <p className="sub">The main reasons, most serious first.</p>
                <ul className="reasons">
                  {factors.map((f) => <li key={f.text}><span className={`sev-dot ${f.tone}`} /><span>{f.text}</span></li>)}
                </ul>
              </>
            ) : <p className="sub">{upi ? report.payment?.summary : "No signs of a fake or unsafe site in the checks Artemis runs."}</p>}
          </section>
          {!upi && categories.length > 0 && (
            <section className="card">
              <h3>Security checks</h3>
              <p className="sub">How the site is set up. {report.duration_ms != null && `Scanned in ${(report.duration_ms / 1000).toFixed(1)} s.`}</p>
              <div className="grades">
                {categories.map((c) => (
                  <div className="grade" key={c.key} title={c.notes.join(" ")}>
                    <b className={c.status}>{c.grade}</b><span>{c.name}</span>
                  </div>
                ))}
              </div>
              <ul className="cat-notes">
                {categories.map((c) => (
                  <li key={c.key}><b>{c.name}</b>{" "}{[...c.notes, c.issues ? `${c.issues} issue${c.issues > 1 ? "s" : ""} found.` : "No issues found."].join(" ")}</li>
                ))}
              </ul>
            </section>
          )}
          {!upi && findings.length > 0 && <Findings findings={findings} />}
        </div>
        <div className="stack">
          {report.payment && <PaymentCard payment={report.payment} />}
          {report.impersonation && !upi && <ImpersonationCard imp={report.impersonation} />}
          {!upi && report.visit && (
            <section className="card">
              <h3>Safe to visit?</h3>
              <ul className="criteria">
                {report.visit.criteria.map((c) => (
                  <li key={c.text} className={c.passed ? "pass" : "fail"}>{c.passed ? c.text : c.problem}</li>
                ))}
              </ul>
            </section>
          )}
          <section className="card">
            <h3>If you already entered details</h3>
            <div className="todo">
              <a href="https://cybercrime.gov.in/" target="_blank" rel="noopener noreferrer">
                <span>Report it on cybercrime.gov.in<small>India's official place to report online fraud.</small></span><Icon name="out" /></a>
              <a href="tel:1930"><span>Lost money? Call 1930<small>The national cyber fraud helpline. Calling quickly gives the best chance of stopping the payment.</small></span><Icon name="out" /></a>
            </div>
          </section>
        </div>
      </div>
      <ReportDialog report={report} open={reporting} onClose={() => setReporting(false)} />
      <RiskDialog report={report} open={warning} onClose={() => setWarning(false)} />
    </article>
  );
}

function Findings({ findings }: { findings: Finding[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="card">
      <h3>Findings <span className="count">{findings.length}</span></h3>
      <p className="sub">Problems in how the site is set up, most serious first.</p>
      <ul className="findings">
        {findings.map((f, i) => (
          <li key={i} className={open === i ? "open" : ""}>
            <div className="finding-row">
              <span className={`sev ${f.severity}`}>{f.severity}</span>
              <div className="finding-text"><Rich text={f.title} /><span className="where">{f.location} · {f.category}</span></div>
              <button className="btn btn-ghost btn-small" type="button" aria-expanded={open === i}
                onClick={() => setOpen(open === i ? null : i)}>{open === i ? "Hide" : "Fix"}</button>
            </div>
            {open === i && <p className="fix"><Rich text={f.fix} /></p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const PAYMENT_KIND: Record<string, string> = { upi: "UPI payment", provider: "Payment page", page: "Payment form on this page" };

export function PaymentCard({ payment }: { payment: Payment }) {
  return (
    <section className={`card level-${payment.level}`}>
      <p className="eyebrow">{PAYMENT_KIND[payment.kind] ?? "Payment"}</p>
      <h3>{payment.verdict}</h3>
      <p className="sub">{payment.summary}</p>
      <Signals signals={payment.signals.filter((s) => s.text !== payment.summary)} />
      <dl className="facts">
        {payment.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </section>
  );
}

function ImpersonationCard({ imp }: { imp: Impersonation }) {
  const page = imp.facts.page;
  const form = !page ? "Page not loaded"
    : page.redirected_to ? `Not checked: leads to ${page.redirected_to}`
    : page.credential_form ? (page.credential_form === "card" ? "Asks for card details" : "Asks for a password")
      + (page.form_built_by_script ? " (added by the page's scripts)" : "")
    : page.rendered ? "No password or card fields" : "No password or card fields in the page's HTML";
  const facts: [string, string][] = [
    ["Registered", imp.facts.registered || "Not published"],
    ["Registrar", imp.facts.registrar || "Unknown"],
    ["Earliest certificate", imp.facts.first_certificate ? `${imp.facts.first_certificate} · ${imp.facts.certificate_source}` : "None found"],
    ["Page checked", page ? page.url : "None"],
    ["Login or payment form", form],
    ["Brand named on page", page && page.brands_named.length ? page.brands_named.join(", ") : "None"],
  ];
  return (
    <section className={`card level-${imp.level}`}>
      <p className="eyebrow">Impersonation check · {imp.registrable}</p>
      <h3>{imp.verdict}</h3>
      <p className="sub">{imp.summary}</p>
      <Signals signals={imp.signals} />
      <dl className="facts">{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <ul className="lists">
        {imp.lists.map((entry) => <li key={entry.name}><span>{entry.name}: {entry.detail}</span><span className={`list-st ${entry.status}`}>{entry.status}</span></li>)}
      </ul>
    </section>
  );
}

function Signals({ signals }: { signals: { tone: string; text: string }[] }) {
  if (!signals.length) return null;
  return <ul className="signals">{signals.map((s) => <li key={s.text} className={s.tone}><Rich text={s.text} /></li>)}</ul>;
}
