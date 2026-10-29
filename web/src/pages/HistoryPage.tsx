// Scans made while signed in.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useAccount } from "../account";
import { clearHistory, getHistory } from "../api";
import type { HistoryItem } from "../types";

export function HistoryPage() {
  const { account, openAuth, setAccount } = useAccount();
  const navigate = useNavigate();
  const [scans, setScans] = useState<HistoryItem[] | null>(null);

  useEffect(() => {
    if (!account) return;
    getHistory().then((d) => setScans(d.scans)).catch(() => setAccount(null));   // the session ended
  }, [account, setAccount]);

  async function clear() {
    if (!confirm("Delete your whole scan history?")) return;
    try { await clearHistory(); setScans([]); } catch { /* leave the list as it is */ }
  }

  return (
    <section>
      <div className="tool-head">
        <p className="eyebrow">Your history</p>
        <h1 className="small-h1">Everything you've checked.</h1>
        <p className="lede">Saved to your account, so you can check a site again from here. Your most recent 200 scans are kept, and you can delete them at any time.</p>
      </div>
      {!account ? (
        <div className="actions"><button className="btn btn-primary" type="button" onClick={() => openAuth("login")}>Log in to see your history</button>
          <button className="btn" type="button" onClick={() => openAuth("signup")}>Create an account</button></div>
      ) : scans === null ? <p className="note">Loading</p> : scans.length === 0 ? (
        <p className="note">No scans yet. Scans you run while signed in appear here.</p>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Checked</th><th>Result</th><th>Verdict</th><th /></tr></thead>
              <tbody>
                {scans.map((s) => (
                  <tr key={`${s.target}-${s.scanned_at}`}>
                    <td className="mono">{new Date(s.scanned_at * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</td>
                    <td className="mono">{s.target}</td>
                    <td><span className={`status ${s.risk_label === "Low" ? "ok" : s.risk_label === "Medium" ? "warn" : s.risk_label ? "bad" : ""}`}>
                      {(s.risk_label || "Offline").toUpperCase()}</span></td>
                    <td>{s.verdict}</td>
                    <td className="right"><button className="btn btn-small" type="button" onClick={() => navigate(`/?scan=${encodeURIComponent(s.target)}`)}>Check again</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="actions"><button className="btn btn-danger" type="button" onClick={clear}>Clear history</button></div>
        </>
      )}
    </section>
  );
}
