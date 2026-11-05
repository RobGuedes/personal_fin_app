import { Link } from "react-router";
import { t } from "../i18n/pt-BR";

export function NotFound() {
  return (
    <section>
      <h1>{t.notFound.title}</h1>
      <div className="card empty">
        <p>{t.notFound.hint}</p>
        <Link to="/">{t.notFound.home}</Link>
      </div>
    </section>
  );
}
