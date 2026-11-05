import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { SYNC_POLL_MS, useSyncStatus } from "../../api/sync";
import { Card } from "../../components/Card";
import { t } from "../../i18n/pt-BR";
import { dateBR } from "../../lib/format";

export type { SyncStatus } from "../../api/sync";
export { SYNC_POLL_MS };

export function Sincronizacao({ pollMs = SYNC_POLL_MS }: { pollMs?: number }) {
  const qc = useQueryClient();
  const status = useSyncStatus(pollMs); // also refreshes every screen when a run ends
  const running = status.data?.running ?? false;
  const [startError, setStartError] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: () => api<{ started: boolean }>("/sync", { method: "POST" }),
    onMutate: () => setStartError(null),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["syncStatus"] }),
    onError: (e) => {
      setStartError(e instanceof Error ? e.message : t.settings.sync.startFailed);
      void qc.invalidateQueries({ queryKey: ["syncStatus"] }); // 409: someone else is running; start polling
    },
  });

  const s = status.data;
  const busy = running || start.isPending;
  const report = !running ? s?.report : null;
  return (
    <Card title={<h2 className="aj-h">{t.settings.sync.title}</h2>}>
      {s && (
        <ul className="aj-list">
          {s.items.map((it, i) => (
            <li key={`${it.name}-${i}`}>
              <span>{it.name}</span>
              <small>{it.last_updated_at ? t.settings.sync.lastUpdate(dateBR(it.last_updated_at)) : t.settings.sync.never}</small>
            </li>
          ))}
          {s.binance_snapshot_at && (
            <li>
              <span>{t.settings.sync.binance}</span>
              <small>{t.settings.sync.lastUpdate(dateBR(s.binance_snapshot_at))}</small>
            </li>
          )}
        </ul>
      )}
      <div className="aj-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={() => start.mutate()}>
          {busy ? t.settings.sync.running : t.settings.sync.now}
        </button>
        {running && s?.step && <span className="aj-step" role="status">{t.settings.sync.step(s.step)}</span>}
      </div>
      {startError && <p className="aj-error" role="alert">{startError}</p>}
      {report && (
        <div className="aj-report">
          <p>{report.errors.length ? t.settings.sync.doneWithErrors : t.settings.sync.done}</p>
          {report.warnings.length > 0 && (
            <>
              <strong>{t.settings.sync.warnings}</strong>
              <ul>{report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </>
          )}
          {report.errors.length > 0 && (
            <>
              <strong className="aj-error">{t.settings.sync.errors}</strong>
              <ul>{report.errors.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </>
          )}
        </div>
      )}
      {s && s.runs.length > 0 && (
        <details className="aj-runs">
          <summary>{t.settings.sync.lastRuns}</summary>
          <ul className="aj-list">
            {s.runs.map((r, i) => (
              <li key={i}>
                <span>{t.settings.sync.run(dateBR(r.started_at), r.error_count)}</span>
                <small>{t.settings.sync.counts(r.inserted ?? 0, r.updated ?? 0, r.deleted ?? 0)}</small>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}
