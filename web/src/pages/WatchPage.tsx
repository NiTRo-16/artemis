// Domain watch: real counts of new lookalike names per brand. Never names a domain.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { getWatchSummary, type WatchSummary } from "../api";
import { dateLocale, useLang, useT } from "../i18n";
import { ComingSoonPage } from "./ComingSoonPage";


export function WatchPage() {
  const t = useT();
  const lang = useLang();
  const when = (seconds: number) => new Date(seconds * 1000).toLocaleString(dateLocale(lang), { dateStyle: "medium", timeStyle: "short" });
  const [data, setData] = useState<WatchSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { getWatchSummary().then(setData).catch((err) => setError((err as Error).message)); }, []);

  if (error) return <section className="tool-head"><p className="eyebrow">{t("Domain watch")}</p><p className="note">{error}</p></section>;
  if (!data) return <section className="tool-head"><p className="eyebrow">{t("Domain watch")}</p><p className="note">{t("Loading")}</p></section>;
  if (!data.public) return <ComingSoonPage tool="watch" />;

  const active = data.brands.filter((b) => b.matches > 0);
  const quiet = data.brands.length - active.length;
  const total = active.reduce((sum, b) => sum + b.matches, 0);
  const forms = active.reduce((sum, b) => sum + b.forms, 0);
  const checked = active.reduce((sum, b) => sum + b.checked, 0);

  return (
    <section>
      <div className="tool-head">
        <h1 className="small-h1">{t("New lookalike names, counted as they appear.")}</h1>
        <p className="lede">{t("Artemis reads public certificate logs and notes new domains whose names resemble a known brand. Each is checked once in a sealed browser.")}</p>
      </div>

      {data.stopped && <p className="form-error" role="alert">{data.last_read ? t("Reading has stopped since {when}. These numbers aren't current.", { when: when(data.last_read) }) : t("Reading has stopped. These numbers aren't current.")}</p>}
      {data.just_started && <p className="note">{t("Domain watch has only just started, so this is less than a full week.")}</p>}

      <div className="watch-totals">
        <div className="card"><b>{total}</b><span>{t(data.just_started ? "Names matched so far" : "Names matched in the last 7 days")}</span></div>
        <div className="card"><b>{checked}</b><span>{t("Checked in a sealed browser")}</span></div>
        <div className="card"><b>{forms}</b><span>{t("Had a login or card form when checked")}</span></div>
      </div>

      <section className="card watch-table-card">
        <h3>{t("By brand")}</h3>
        {active.length === 0 ? <p className="sub">{t("No matches for any of the {count} brands yet.", { count: data.brands.length })}</p> : (
          <div className="table-wrap">
            <table className="watch-table">
              <thead><tr><th scope="col">{t("Brand")}</th><th scope="col">{t("Names")}</th><th scope="col">{t("Checked")}</th><th scope="col">{t("Login or card form")}</th><th scope="col">{t("On a blocklist")}</th></tr></thead>
              <tbody>{active.map((b) => <tr key={b.brand}><th scope="row">{b.brand}</th><td>{b.matches}</td><td>{b.checked}</td><td>{b.forms}</td><td>{b.listed}</td></tr>)}</tbody>
            </table>
          </div>
        )}
        {active.length > 0 && quiet > 0 && <p className="small">{t("The other {count} brands have no matches in this period.", { count: quiet })}</p>}
      </section>

      <div className="stack watch-notes">
        <p className="note small"><b>{t("What a match means.")}</b> {t("The name resembles a brand. Many matches are innocent, such as a real local business or a reseller, so these are counts and no domains are listed. A site can also hide from our check, so \"no form\" never means safe.")}</p>
        <p className="note small"><b>{t("What this covers.")}</b> {t("Only certificates in these logs: {logs}. Sites with certificates elsewhere can be missed.", { logs: data.logs.join(", ") })}{data.last_read && ` ${t("Last read {when}.", { when: when(data.last_read) })}`}{data.last_gap && ` ${t("Some entries were skipped on {when}, when reading fell behind.", { when: when(data.last_gap) })}`}</p>
      </div>

      <div className="actions"><Link className="btn btn-primary" to="/">{t("Scan a site")}</Link></div>
    </section>
  );
}
