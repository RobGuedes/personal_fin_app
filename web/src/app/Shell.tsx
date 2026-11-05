import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { SYNC_POLL_MS, useSyncStatus } from "../api/sync";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { ServerBanner } from "../components/ServerBanner";
import { t } from "../i18n/pt-BR";

/** 24×24 outline paths, stroked in currentColor (no icon library, no external assets). */
const ICONS = {
  home: "M3 10.5 12 3l9 7.5M5.5 8.5V20h13V8.5M10 20v-6h4v6",
  review: "M3 13h5l1.5 3h5L16 13h5M5 5h14l2 8v6H3v-6l2-8ZM9 8.5l2 2 4-4",
  list: "M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01",
  chart: "M4 20V10M10 20V4M16 20v-7M21 20H3",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 13.5l1.6 1.2-1.8 3.1-1.9-.6a7 7 0 0 1-1.7 1l-.4 2h-3.6l-.4-2a7 7 0 0 1-1.7-1l-1.9.6L5 14.7l1.6-1.2a7 7 0 0 1 0-2L5 10.3l1.8-3.1 1.9.6a7 7 0 0 1 1.7-1l.4-2h3.6l.4 2a7 7 0 0 1 1.7 1l1.9-.6 1.8 3.1-1.6 1.2a7 7 0 0 1 0 2Z",
  wealth: "M3 9.5 12 4l9 5.5M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20.5h18",
} as const;

function NavIcon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={ICONS[name]} />
    </svg>
  );
}

const ITEMS = [
  { to: "/", label: t.nav.home, key: "i", end: true, icon: "home" },
  { to: "/revisar", label: t.nav.review, key: "r", icon: "review" },
  { to: "/transacoes", label: t.nav.transactions, key: "t", icon: "list" },
  { to: "/panorama", label: t.nav.overview, icon: "chart" },
  { to: "/patrimonio", label: t.nav.wealth, icon: "wealth" },
] as const;

function isTyping(el: EventTarget | null): boolean {
  const e = el as HTMLElement | null;
  if (!e) return false;
  return e.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(e.tagName);
}

function useShortcuts() {
  const navigate = useNavigate();
  const pendingG = useRef<number | null>(null);
  useEffect(() => {
    const routes: Record<string, string> = { i: "/", r: "/revisar", t: "/transacoes" };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.metaKey || ev.ctrlKey || ev.altKey || isTyping(ev.target)) return;
      if (pendingG.current !== null) {
        window.clearTimeout(pendingG.current);
        pendingG.current = null;
        const dest = routes[ev.key];
        if (dest) {
          ev.preventDefault();
          navigate(dest);
          return;
        }
      }
      if (ev.key === "g") {
        pendingG.current = window.setTimeout(() => (pendingG.current = null), 1000);
      } else if (ev.key === "/") {
        const input = document.querySelector<HTMLInputElement>("[data-search]");
        if (input) {
          ev.preventDefault();
          input.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);
}

function NavItems({ idPrefix }: { idPrefix: string }) {
  return (
    <>
      {ITEMS.map((it) => (
        <NavLink key={idPrefix + it.to} to={it.to} end={"end" in it ? it.end : false} className="nav-link">
          <NavIcon name={it.icon} />
          <span>{it.label}</span>
        </NavLink>
      ))}
    </>
  );
}

const SETTINGS_ITEM = { to: "/ajustes", label: t.nav.settings, icon: "gear" } as const;

export function Shell({ syncPollMs = SYNC_POLL_MS }: { syncPollMs?: number }) {
  useShortcuts();
  useSyncStatus(syncPollMs); // a sync that ends refreshes the open page, whichever it is
  const location = useLocation();
  return (
    <div className="shell">
      <nav className="sidebar" aria-label={t.nav.main}>
        <div className="brand">{t.appName}</div>
        <NavItems idPrefix="side" />
        <NavLink to={SETTINGS_ITEM.to} className="nav-link nav-settings">
          <NavIcon name={SETTINGS_ITEM.icon} />
          <span>{SETTINGS_ITEM.label}</span>
        </NavLink>
      </nav>
      <main className="content">
        <header className="phone-header">
          <NavLink to={SETTINGS_ITEM.to} className="gear" aria-label={SETTINGS_ITEM.label}>
            <NavIcon name={SETTINGS_ITEM.icon} />
          </NavLink>
        </header>
        <ServerBanner />
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
      <nav className="tabbar" aria-label={t.nav.main}>
        <NavItems idPrefix="tab" />
      </nav>
    </div>
  );
}
