import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { t } from "../i18n/pt-BR";

export interface ToastAction {
  label: string;
  onClick: () => void;
}
interface ToastItem {
  id: number;
  message: string;
  action?: ToastAction;
}
interface ToastApi {
  /** Returns the toast id, for `dismiss`. */
  show: (message: string, opts?: { action?: ToastAction }) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

export function ToastProvider({ children, durationMs = 6000 }: { children: ReactNode; durationMs?: number }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems((xs) => xs.filter((x) => x.id !== id));
  }, []);
  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach((h) => window.clearTimeout(h));
      pending.clear();
    };
  }, []);
  const show = useCallback<ToastApi["show"]>(
    (message, opts) => {
      const id = nextId.current++;
      setItems((xs) => [...xs, { id, message, action: opts?.action }]);
      timers.current.set(id, window.setTimeout(() => dismiss(id), durationMs));
      return id;
    },
    [dismiss, durationMs],
  );
  const api = useMemo(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((it) => (
          <div className="toast" key={it.id}>
            <span>{it.message}</span>
            {it.action && (
              <button
                type="button"
                onClick={() => {
                  it.action!.onClick();
                  dismiss(it.id);
                }}
              >
                {it.action.label}
              </button>
            )}
            <button type="button" className="toast-x" aria-label={t.close} onClick={() => dismiss(it.id)}>
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
