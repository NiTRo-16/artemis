import { Link, useLocation, useNavigate } from "react-router";
import { Icon } from "../components/ui";

export function NotFoundPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  return (
    <section className="not-found">
      <div className="ring nf-ring" aria-hidden="true">
        <svg viewBox="0 0 170 170">
          <circle className="ring-track" cx="85" cy="85" r="74" />
          <circle className="ring-fill" cx="85" cy="85" r="74" strokeDasharray="116 465" />
        </svg>
        <div className="ring-num"><b>404</b><span>NOT FOUND</span></div>
      </div>
      <div className="nf-text">
        <h1 className="small-h1">This address doesn't lead anywhere.</h1>
        <div className="target nf-target"><Icon name="link" className="icon dim" /><span>{pathname}</span></div>
        <div className="actions">
          <Link className="btn btn-primary" to="/">Scan a site</Link>
          <button className="btn" type="button" onClick={() => navigate(-1)}>Go back</button>
        </div>
      </div>
    </section>
  );
}
