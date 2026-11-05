import { Component, type ErrorInfo, type ReactNode } from "react";
import { t } from "../i18n/pt-BR";

/** Catches a render error in one screen so the shell (nav, banner) keeps working. Key it by route. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Erro ao desenhar a tela", error, info.componentStack); // local only, no telemetry
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section>
        <div className="card empty" role="alert">
          <strong>{t.crash.title}</strong>
          <p>{t.crash.hint}</p>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            {t.crash.reload}
          </button>
        </div>
      </section>
    );
  }
}
