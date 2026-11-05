import type { ReactNode } from "react";
import { Link } from "react-router";

interface CardProps {
  title?: ReactNode;
  /** Right side of the header: a short label ("6 meses", "82%"). A linked, titled card gets a chevron when omitted. */
  action?: ReactNode;
  /** The whole card becomes one link. */
  href?: string;
  className?: string;
  children?: ReactNode;
}

export function Card({ title, action, href, className = "", children }: CardProps) {
  const chevron = href !== undefined && title !== undefined && action === undefined;
  const head =
    title !== undefined || action !== undefined ? (
      <div className="card-head">
        {title !== undefined && <span className="card-title">{title}</span>}
        <span className="card-action">
          {action}
          {chevron && <span aria-hidden="true">›</span>}
        </span>
      </div>
    ) : null;
  if (href) {
    return (
      <Link to={href} className={`card card-link ${className}`}>
        {head}
        {children}
      </Link>
    );
  }
  return (
    <section className={`card ${className}`}>
      {head}
      {children}
    </section>
  );
}
