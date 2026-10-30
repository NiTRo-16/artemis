// The full result of a scan, at /scan/<id> (kept 24 hours) and, read-only, at /r/<id> when shared.
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useAccount } from "../account";
import { getScan, getShared, shareScan } from "../api";
import { tk, translate, useT } from "../i18n";
import { ReportDialog, RiskDialog } from "../components/ReportDialogs";
import { Icon, Rich, SafetyBanner } from "../components/ui";
import { reportable, riskFactors, riskName, riskTone, safeUrl } from "../report";
import type { Finding, Impersonation, Payment, Report } from "../types";

export function ResultPage() {
  const { id = "" } = useParams();
  const state = useLocation().state as { report?: Report } | null;
  const [report, setReport] = useState<Report | null>(state?.report ?? null);
  const [error, setError] = useState("");
  const t = useT();

  useEffect(() => {
    if (report || id === "upi") return;
    getScan(id).then((s) => s.report ? setReport(s.report) : setError(translate(s.error || "This scan hasn't finished.")))
      .catch((err) => setError((err as Error).message));
  }, [id, report]);

  if (!report) {
    return <Missing text={error || t(id === "upi" ? "UPI checks aren't kept. Check the link again." : "Loading the result")} />;
  }
  return <ResultView report={report} shareId={id === "upi" ? null : id} />;
}

export function SharedPage() {
  const { id = "" } = useParams();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const t = useT();
  useEffect(() => { getShared(id).then(setReport).catch((err) => setError((err as Error).message)); }, [id]);
  if (!report) return <Missing text={error || t("Loading the shared result")} />;
  return <ResultView report={report} shareId={null} shared />;
}

function Missing({ text }: { text: string }) {
  const t = useT();
  return (
    <div className="tool-head">
      <h1 className="small-h1">{text}</h1>
      <Link className="btn btn-primary" to="/">{t("Scan a site")}</Link>
    </div>
  );
}

export function ResultView({ report, shareId, shared = false }: { report: Report; shareId: string | null; shared?: boolean }) {
  const { settings } = useAccount();
  const t = useT();
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
      try { await navigator.clipboard.writeText(link); setShareText(t("Link copied: {link}", { link })); }
      catch { setShareText(t("Share this link: {link}", { link })); }
    } catch (err) {
      setShareText((err as Error).message);
    }
  }

  return (
    <article>
      <div className="result-head">
        <div>
          {shared && <p className="eyebrow">{t("Shared result")}</p>}
          <h2 className="result-target">{report.domain}</h2>
          <div className="verdict-row">
            {report.risk && <span className={`verdict ${tone}`}><span className="dot" />{t(riskName(report.risk.label)).toUpperCase()}
              {report.risk.score != null && ` · ${report.risk.score}`}</span>}
            {!upi && report.resolves === false && <span className="verdict none"><span className="dot" />{t("OFFLINE")}</span>}
            <span className="main-result">{t((upi ? report.payment?.verdict : report.impersonation?.verdict) ?? "")}</span>
          </div>
        </div>
        <div className="actions">
          {shareId && <button className="btn" type="button" onClick={share}><Icon name="share" />{t("Share result")}</button>}
          {reportable(report) && <button className="btn" type="button" onClick={() => setReporting(true)}>
            <Icon name="flag" />{t(upi ? "Report this UPI ID" : "Report site")}</button>}
          {url && report.visit?.allowed && <a className="btn btn-primary" href={url} target={settings.same_tab ? "_self" : "_blank"}
            rel="noopener noreferrer">{t("Continue to {site}", { site: report.domain })}</a>}
          {url && !report.visit?.allowed && <button className="btn btn-danger" type="button" onClick={() => setWarning(true)}>{t("Continue anyway")}</button>}
        </div>
      </div>
      {shareText && <p className="share-note" role="status">{shareText}</p>}

      <div className="grid-2">
        <div className="stack">
          <section className="card">
            <h3>{t(factors.length ? "Why it's risky" : "What we found")}</h3>
            {factors.length ? (
              <>
                <ul className="reasons">
                  {factors.map((f) => <li key={f.text}><span className={`sev-dot ${f.tone}`} /><span>{t(f.text)}</span></li>)}
                </ul>
              </>
            ) : <p className="sub">{t(upi ? report.payment?.summary ?? "" : "No signs of a fake or unsafe site in the checks Artemis runs.")}</p>}
          </section>
          {!upi && categories.length > 0 && (
            <section className="card">
              <h3>{t("Security checks")}</h3>
              <div className="grades">
                {categories.map((c) => (
                  <div className="grade" key={c.key} title={c.notes.join(" ")}>
                    <b className={c.status}>{c.grade}</b><span>{t(c.name)}</span>
                  </div>
                ))}
              </div>
              <ul className="cat-notes">
                {categories.map((c) => (
                  <li key={c.key}><b>{t(c.name)}</b>{" "}{[...c.notes, c.issues ? `${c.issues} issue${c.issues > 1 ? "s" : ""} found.` : t("No issues found.")].join(" ")}</li>
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
              <h3>{t("Safe to visit?")}</h3>
              <ul className="criteria">
                {report.visit.criteria.map((c) => (
                  <li key={c.text} className={c.passed ? "pass" : "fail"}>{t(c.passed ? c.text : c.problem)}</li>
                ))}
              </ul>
            </section>
          )}
          <section className="card">
            <h3>{t("If you already entered details")}</h3>
            <div className="todo">
              <a href="https://cybercrime.gov.in/" target="_blank" rel="noopener noreferrer">
                <span>{t("Report it on cybercrime.gov.in")}</span><Icon name="out" /></a>
              <a href="tel:1930"><span>{t("Lost money? Call 1930")}<small>{t("National cyber fraud helpline")}</small></span><Icon name="out" /></a>
            </div>
          </section>
        </div>
      </div>
      <ReportDialog report={report} open={reporting} onClose={() => setReporting(false)} />
      <RiskDialog report={report} open={warning} onClose={() => setWarning(false)} />
    </article>
  );
}

const SEVERITY: Record<string, string> = { critical: tk("critical"), high: tk("high"), medium: tk("medium"), low: tk("low"), info: tk("info") };

function Findings({ findings }: { findings: Finding[] }) {
  const t = useT();
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="card">
      <h3>{t("Findings")} <span className="count">{findings.length}</span></h3>
      <ul className="findings">
        {findings.map((f, i) => (
          <li key={i} className={open === i ? "open" : ""}>
            <div className="finding-row">
              <span className={`sev ${f.severity}`}>{t(SEVERITY[f.severity] ?? f.severity)}</span>
              <div className="finding-text"><Rich text={f.title} /><span className="where">{f.location} · {f.category}</span></div>
              <button className="btn btn-ghost btn-small" type="button" aria-expanded={open === i}
                onClick={() => setOpen(open === i ? null : i)}>{t(open === i ? "Hide" : "Fix")}</button>
            </div>
            {open === i && <p className="fix"><Rich text={f.fix} /></p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const PAYMENT_KIND: Record<string, string> = { upi: tk("UPI payment"), provider: tk("Payment page"), page: tk("Payment form on this page") };

export function PaymentCard({ payment }: { payment: Payment }) {
  const t = useT();
  return (
    <section className={`card level-${payment.level}`}>
      {payment.kind === "upi" && <SafetyBanner level={payment.level} />}
      <p className="eyebrow">{t(PAYMENT_KIND[payment.kind] ?? "Payment")}</p>
      <h3>{t(payment.verdict)}</h3>
      <p className="sub">{t(payment.summary)}</p>
      <Signals signals={payment.signals.filter((s) => s.text !== payment.summary)} />
      <dl className="facts">
        {payment.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </section>
  );
}

function ImpersonationCard({ imp }: { imp: Impersonation }) {
  const t = useT();
  const page = imp.facts.page;
  const form = !page ? t("Page not loaded")
    : page.redirected_to ? t("Not checked: leads to {site}", { site: page.redirected_to })
    : page.credential_form ? t(page.credential_form === "card" ? "Asks for card details" : "Asks for a password")
      + (page.form_built_by_script ? t(" (added by the page's scripts)") : "")
    : t(page.rendered ? "No password or card fields" : "No password or card fields in the page's HTML");
  const facts: [string, string][] = [
    [t("Registered"), imp.facts.registered || t("Not published")],
    [t("Registrar"), imp.facts.registrar || t("Unknown")],
    [t("Earliest certificate"), imp.facts.first_certificate ? `${imp.facts.first_certificate} · ${imp.facts.certificate_source}` : t("None found")],
    [t("Page checked"), page ? page.url : t("None")],
    [t("Login or payment form"), form],
    [t("Brand named on page"), page && page.brands_named.length ? page.brands_named.join(", ") : t("None")],
  ];
  return (
    <section className={`card level-${imp.level}`}>
      <p className="eyebrow">{t("Impersonation check · {domain}", { domain: imp.registrable })}</p>
      <h3>{t(imp.verdict)}</h3>
      <p className="sub">{t(imp.summary)}</p>
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
