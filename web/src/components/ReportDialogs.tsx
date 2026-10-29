// "Report this site" and the "Continue anyway" warning for risky sites.
import { useState, type FormEvent } from "react";
import { useAccount } from "../account";
import * as backend from "../api";
import { reportTarget, riskFactors, safeUrl } from "../report";
import type { Report } from "../types";
import { Dialog } from "./ui";

const CATEGORIES = [
  ["phishing", "Phishing or a fake login page"],
  ["malware", "Malware or harmful downloads"],
  ["payment", "Payment or shopping scam"],
  ["other", "Something else"],
] as const;

export function ReportDialog({ report, open, onClose }: { report: Report; open: boolean; onClose: () => void }) {
  const upi = report.kind === "upi";
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
    <Dialog open={open} onClose={onClose} title={upi ? "Report this UPI ID" : "Report this site"}>
      <p className="target-line">{target}</p>
      {sent ? (
        <div role="status"><p className="sent">Thanks, your report was sent</p><p className="note">Team Artemis will review it.</p></div>
      ) : (
        <form onSubmit={submit} noValidate>
          <fieldset className="choices">
            <legend>What's wrong with it?</legend>
            {CATEGORIES.map(([value, label]) => (
              <label className="choice" key={value}>
                <input type="radio" name="report-category" checked={category === value} onChange={() => setCategory(value)} /> {label}
              </label>
            ))}
          </fieldset>
          <label className="field">What happened? (optional)
            <textarea className="input" maxLength={1000} value={details} onChange={(e) => setDetails(e.target.value)} />
          </label>
          <p className="note small">Team Artemis reviews every report. A report doesn't change this site's result by itself. Don't include passwords, card numbers or other personal details.</p>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="actions">
            <button className="btn btn-primary" type="submit" disabled={busy}>Send report</button>
            <button className="btn btn-ghost" type="button" onClick={onClose}>Cancel</button>
          </div>
        </form>
      )}
      <section className="dlg-section">
        <h3>Report it officially too</h3>
        <ul className="official">
          {upi ? <li>Your UPI app or bank<span>Report the UPI ID from the payment screen or your app's help section.</span></li>
            : <li><a href={google} target="_blank" rel="noopener noreferrer">Google Safe Browsing</a>
                <span>Adds the site to the warnings shown in Chrome, Firefox and Safari.</span></li>}
          <li><a href="https://cybercrime.gov.in/" target="_blank" rel="noopener noreferrer">National Cyber Crime Reporting Portal</a>
            <span>India's official place to report online fraud.</span></li>
          <li>Lost money? Call <a href="tel:1930">1930</a>
            <span>The national cyber fraud helpline. Calling quickly gives the best chance of stopping the payment.</span></li>
        </ul>
      </section>
    </Dialog>
  );
}

export function RiskDialog({ report, open, onClose }: { report: Report; open: boolean; onClose: () => void }) {
  const { settings } = useAccount();
  const url = safeUrl(report.visit?.url);
  return (
    <Dialog open={open} onClose={onClose} title="This site is high risk">
      <p className="target-line">{url}</p>
      <ul className="risk-list">
        {riskFactors(report).map((item) => <li key={item.text} className={item.tone}>{item.text}</li>)}
      </ul>
      <p className="note">Don't enter passwords, card details or personal information unless you're sure this is the site you meant to visit.</p>
      <p className="note">If you continue, you visit this site at your own risk. Artemis isn't responsible for what happens there. See
        the <a href="/terms" target="_blank" rel="noopener">Terms and conditions</a>.</p>
      <div className="actions">
        <button className="btn btn-primary" type="button" onClick={onClose}>Go back</button>
        {url && <a className="btn btn-danger" href={url} target={settings.same_tab ? "_self" : "_blank"}
          rel="noopener noreferrer" onClick={onClose}>Continue to site</a>}
      </div>
    </Dialog>
  );
}
