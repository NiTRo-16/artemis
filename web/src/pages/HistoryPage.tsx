// Scans made while signed in.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useAccount } from "../account";
import { clearHistory, getHistory } from "../api";
import { dateLocale, useLang, useT } from "../i18n";
import type { HistoryItem } from "../types";

export function HistoryPage() {
  const { account, openAuth, setAccount } = useAccount();
  const navigate = useNavigate();
  const t = useT();
  const lang = useLang();
  const [scans, setScans] = useState<HistoryItem[] | null>(null);

  useEffect(() => {
    if (!account) return;
    getHistory().then((d) => setScans(d.scans)).catch(() => setAccount(null));   // the session ended
  }, [account, setAccount]);

  async function clear() {
    if (!confirm(t("Delete your whole scan history?"))) return;
    try { await clearHistory(); setScans([]); } catch { /* leave the list as it is */ }
  }

  return (
    <section>
      <div className="tool-head">
        <h1 className="small-h1">{t("Everything you've checked.")}</h1>
      </div>
      {!account ? (
        <div className="actions"><button className="btn btn-primary" type="button" onClick={() => openAuth("login")}>{t("Log in to see your history")}</button>
          <button className="btn" type="button" onClick={() => openAuth("signup")}>{t("Create an account")}</button></div>
      ) : scans === null ? <p className="note">{t("Loading")}</p> : scans.length === 0 ? (
        <p className="note">{t("No scans yet.")}</p>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("When")}</th><th>{t("Checked")}</th><th>{t("Result")}</th><th>{t("Verdict")}</th><th /></tr></thead>
              <tbody>
                {scans.map((s) => (
                  <tr key={`${s.target}-${s.scanned_at}`}>
                    <td className="mono">{new Date(s.scanned_at * 1000).toLocaleString(dateLocale(lang), { dateStyle: "medium", timeStyle: "short" })}</td>
                    <td className="mono">{s.target}</td>
                    <td><span className={`status ${s.risk_label === "Low" ? "ok" : s.risk_label === "Medium" ? "warn" : s.risk_label ? "bad" : ""}`}>
                      {t(s.risk_label || "Offline").toUpperCase()}</span></td>
                    <td>{t(s.verdict)}</td>
                    <td className="right"><button className="btn btn-small" type="button" onClick={() => navigate(`/?scan=${encodeURIComponent(s.target)}`)}>{t("Check again")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="actions"><button className="btn btn-danger" type="button" onClick={clear}>{t("Clear history")}</button></div>
        </>
      )}
    </section>
  );
}
