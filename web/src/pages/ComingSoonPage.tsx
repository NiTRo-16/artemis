// Tools on the roadmap. Each page says plainly what the tool will do; nothing here is sample data.
import { Link } from "react-router";

const TOOLS = {
  watch: {
    eyebrow: "Domain watch", title: "New lookalike sites, spotted as they appear.",
    lede: "Artemis will read public certificate logs and flag new domains that copy Indian banks, payment apps and popular services, often before any blocklist has them. Organisations will be able to watch for copies of their own brand.",
  },
  developers: {
    eyebrow: "API", title: "Use the same checks in your own app.",
    lede: "Send a link or UPI ID and get the risk level and the reasons back as JSON, with an API key and a free daily allowance.",
  },
};

export function ComingSoonPage({ tool }: { tool: keyof typeof TOOLS }) {
  const t = TOOLS[tool];
  return (
    <section className="tool-head">
      <p className="eyebrow">{t.eyebrow} <span className="soon">COMING SOON</span></p>
      <h1 className="small-h1">{t.title}</h1>
      <p className="lede">{t.lede}</p>
      <p className="note">This tool is being built. Until then, you can check websites and UPI links from the scan page.</p>
      <Link className="btn btn-primary" to="/">Go to the scan page</Link>
    </section>
  );
}
