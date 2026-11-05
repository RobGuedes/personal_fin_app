import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { t } from "../i18n/pt-BR";

export function ServerBanner() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ ok: boolean }>("/health"), retry: false, refetchInterval: 15000 });
  if (!health.isError) return null;
  return (
    <div className="banner" role="alert">
      {t.serverDown}
    </div>
  );
}
