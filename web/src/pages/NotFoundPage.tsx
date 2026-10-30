import { Link, useLocation, useNavigate } from "react-router";
import { Icon } from "../components/ui";
import { useT } from "../i18n";

export function NotFoundPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const t = useT();
  return (
    <section className="not-found">
      <div className="ring nf-ring" aria-hidden="true">
        <svg viewBox="0 0 170 170">
          <circle className="ring-track" cx="85" cy="85" r="74" />
          <circle className="ring-fill" cx="85" cy="85" r="74" strokeDasharray="116 465" />
        </svg>
        <div className="ring-num"><b>404</b><span>{t("NOT FOUND")}</span></div>
      </div>
      <div className="nf-text">
        <h1 className="small-h1">{t("This address doesn't lead anywhere.")}</h1>
        <div className="target nf-target"><Icon name="link" className="icon dim" /><span>{pathname}</span></div>
        <div className="actions">
          <Link className="btn btn-primary" to="/">{t("Scan a site")}</Link>
          <button className="btn" type="button" onClick={() => navigate(-1)}>{t("Go back")}</button>
        </div>
      </div>
    </section>
  );
}
