// "Report this site" and the "Continue anyway" warning for risky sites.
import { useState, type FormEvent } from "react";
import { useAccount } from "../account";
import * as backend from "../api";
import { tk, useT, withSlots } from "../i18n";
import { reportTarget, riskFactors, safeUrl } from "../report";
import type { Report } from "../types";
import { Dialog } from "./ui";

const CATEGORIES = [
  ["phishing", tk("Phishing or a fake login page")],
  ["malware", tk("Malware or harmful downloads")],
  ["payment", tk("Payment or shopping scam")],
  ["other", tk("Something else")],
] as const;

export function ReportDialog({ report, open, onClose }: { report: Report; open: boolean; onClose: () => void }) {
  const upi = report.kind === "upi";
  const t = useT();
  const target = reportTarget(report);
  const [category, setCategory] = useState<string>(upi || (report.payment && report.payment.level !== "clear") ? "payment" : "phishing");
  const [details, setDetails] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const google = `https://safebrowsing.google.com/safebrowsing/${category === "malware" ? "report_badware" : "report_phish"}/?url=${encodeURIComponent(target)}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await backend.sendReport(target, category, details);
      setSent(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t(upi ? "Report this UPI ID" : "Report this site")}>
      <p className="target-line">{target}</p>
      {sent ? (
        <div role="status"><p className="sent">{t("Thanks, your report was sent")}</p><p className="note">{t("Team Artemis will review it.")}</p></div>
      ) : (
        <form onSubmit={submit} noValidate>
          <fieldset className="choices">
            <legend>{t("What's wrong with it?")}</legend>
            {CATEGORIES.map(([value, label]) => (
              <label className="choice" key={value}>
                <input type="radio" name="report-category" checked={category === value} onChange={() => setCategory(value)} /> {t(label)}
              </label>
            ))}
          </fieldset>
          <label className="field">{t("What happened? (optional)")}
            <textarea className="input" maxLength={1000} value={details} onChange={(e) => setDetails(e.target.value)} />
          </label>
          <p className="note small">{t("Team Artemis reviews every report. A report doesn't change this site's result by itself. Don't include passwords, card numbers or other personal details.")}</p>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="actions">
            <button className="btn btn-primary" type="submit" disabled={busy}>{t("Send report")}</button>
            <button className="btn btn-ghost" type="button" onClick={onClose}>{t("Cancel")}</button>
          </div>
        </form>
      )}
      <section className="dlg-section">
        <h3>{t("Report it officially too")}</h3>
        <ul className="official">
          {upi ? <li>{t("Your UPI app or bank")}<span>{t("Report the UPI ID from the payment screen or your app's help section.")}</span></li>
            : <li><a href={google} target="_blank" rel="noopener noreferrer">Google Safe Browsing</a>
                <span>{t("Adds the site to the warnings shown in Chrome, Firefox and Safari.")}</span></li>}
          <li><a href="https://cybercrime.gov.in/" target="_blank" rel="noopener noreferrer">{t("National Cyber Crime Reporting Portal")}</a>
            <span>{t("India's official place to report online fraud.")}</span></li>
          <li>{withSlots(t("Lost money? Call {phone}"), { phone: <a key="phone" href="tel:1930">1930</a> })}
            <span>{t("The national cyber fraud helpline. Calling quickly gives the best chance of stopping the payment.")}</span></li>
        </ul>
      </section>
    </Dialog>
  );
}

export function RiskDialog({ report, open, onClose }: { report: Report; open: boolean; onClose: () => void }) {
  const { settings } = useAccount();
  const url = safeUrl(report.visit?.url);
  const t = useT();
  return (
    <Dialog open={open} onClose={onClose} title={t("This site is high risk")}>
      <p className="target-line">{url}</p>
      <ul className="risk-list">
        {riskFactors(report).map((item) => <li key={item.text} className={item.tone}>{t(item.text)}</li>)}
      </ul>
      <p className="note">{t("Don't enter passwords, card details or personal information unless you're sure this is the site you meant to visit.")}</p>
      <p className="note">{withSlots(t("If you continue, you visit this site at your own risk. Artemis isn't responsible for what happens there. See the {terms}."),
        { terms: <a key="terms" href="/terms" target="_blank" rel="noopener">{t("Terms and conditions")}</a> })}</p>
      <div className="actions">
        <button className="btn btn-primary" type="button" onClick={onClose}>{t("Go back")}</button>
        {url && <a className="btn btn-danger" href={url} target={settings.same_tab ? "_self" : "_blank"}
          rel="noopener noreferrer" onClick={onClose}>{t("Continue to site")}</a>}
      </div>
    </Dialog>
  );
}
