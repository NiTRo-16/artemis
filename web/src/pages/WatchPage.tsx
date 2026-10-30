// Domain watch: real counts of new lookalike names per brand. Never names a domain.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { getWatchSummary, type WatchSummary } from "../api";
import { ComingSoonPage } from "./ComingSoonPage";

const when = (seconds: number) => new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export function WatchPage() {
  const [data, setData] = useState<WatchSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { getWatchSummary().then(setData).catch((err) => setError((err as Error).message)); }, []);

  if (error) return <section className="tool-head"><p className="eyebrow">Domain watch</p><p className="note">{error}</p></section>;
  if (!data) return <section className="tool-head"><p className="eyebrow">Domain watch</p><p className="note">Loading</p></section>;
  if (!data.public) return <ComingSoonPage tool="watch" />;

  const active = data.brands.filter((b) => b.matches > 0);
  const quiet = data.brands.length - active.length;
  const total = active.reduce((sum, b) => sum + b.matches, 0);
  const forms = active.reduce((sum, b) => sum + b.forms, 0);
  const checked = active.reduce((sum, b) => sum + b.checked, 0);

  return (
    <section>
      <div className="tool-head">
        <h1 className="small-h1">New lookalike names, counted as they appear.</h1>
        <p className="lede">Artemis reads public certificate logs and notes new domains whose names resemble a known brand. Each is checked once in a sealed browser.</p>
      </div>

      {data.stopped && <p className="form-error" role="alert">Reading has stopped{data.last_read ? ` since ${when(data.last_read)}` : ""}. These numbers aren't current.</p>}
      {data.just_started && <p className="note">Domain watch has only just started, so this is less than a full week.</p>}

      <div className="watch-totals">
        <div className="card"><b>{total}</b><span>{data.just_started ? "Names matched so far" : "Names matched in the last 7 days"}</span></div>
        <div className="card"><b>{checked}</b><span>Checked in a sealed browser</span></div>
        <div className="card"><b>{forms}</b><span>Had a login or card form when checked</span></div>
      </div>

      <section className="card watch-table-card">
        <h3>By brand</h3>
        {active.length === 0 ? <p className="sub">No matches for any of the {data.brands.length} brands yet.</p> : (
          <div className="table-wrap">
            <table className="watch-table">
              <thead><tr><th scope="col">Brand</th><th scope="col">Names</th><th scope="col">Checked</th><th scope="col">Login or card form</th><th scope="col">On a blocklist</th></tr></thead>
              <tbody>{active.map((b) => <tr key={b.brand}><th scope="row">{b.brand}</th><td>{b.matches}</td><td>{b.checked}</td><td>{b.forms}</td><td>{b.listed}</td></tr>)}</tbody>
            </table>
          </div>
        )}
        {active.length > 0 && quiet > 0 && <p className="small">The other {quiet} brands have no matches in this period.</p>}
      </section>

      <div className="stack watch-notes">
        <p className="note small"><b>What a match means.</b> The name resembles a brand. Many matches are innocent, such as a real local business or a reseller, so these are counts and no domains are listed. A site can also hide from our check, so "no form" never means safe.</p>
        <p className="note small"><b>What this covers.</b> Only certificates in these logs: {data.logs.join(", ")}. Sites with certificates elsewhere can be missed.{data.last_read && ` Last read ${when(data.last_read)}.`}{data.last_gap && ` Some entries were skipped on ${when(data.last_gap)}, when reading fell behind.`}</p>
      </div>

      <div className="actions"><Link className="btn btn-primary" to="/">Scan a site</Link></div>
    </section>
  );
}
