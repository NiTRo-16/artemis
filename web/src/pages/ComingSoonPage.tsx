// Tools on the roadmap. Each page says plainly what the tool will do; nothing here is sample data.
import { Link } from "react-router";
import { tk, useT } from "../i18n";

const TOOLS = {
  watch: {
    title: tk("New lookalike sites, spotted as they appear."),
    lede: tk("Artemis will read public certificate logs and flag new domains that copy Indian banks, payment apps and popular services, often before any blocklist has them. Organisations will be able to watch for copies of their own brand."),
  },
  developers: {
    title: tk("Use the same checks in your own app."),
    lede: tk("Send a link or UPI ID and get the risk level and the reasons back as JSON, with an API key and a free daily allowance."),
  },
};

export function ComingSoonPage({ tool }: { tool: keyof typeof TOOLS }) {
  const page = TOOLS[tool];
  const t = useT();
  return (
    <section className="tool-head">
      <span className="soon">{t("COMING SOON")}</span>
      <h1 className="small-h1">{t(page.title)}</h1>
      <p className="lede">{t(page.lede)}</p>
      <Link className="btn btn-primary" to="/">{t("Scan a site")}</Link>
    </section>
  );
}
