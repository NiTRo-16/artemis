import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <section className="tool-head">
      <p className="eyebrow">Not found</p>
      <h1 className="small-h1">There's no page at this address.</h1>
      <Link className="btn btn-primary" to="/">Go to the scan page</Link>
    </section>
  );
}
