import { t } from "../../i18n/pt-BR";
import { brl } from "../../lib/format";

const W = 60;
const H = 20;

/** 12-point trend line; decorative at a glance, with a text alternative carrying the values. */
export function Sparkline({ values, color, label }: { values: number[]; color: string; label: string }) {
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? W / (values.length - 1) : 0;
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(H - 2 - (Math.max(0, v) / max) * (H - 4)).toFixed(1)}`);
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={t.panorama.sparkAria(label)}>
      <title>{`${t.panorama.sparkAria(label)}: ${values.map((v) => brl(v)).join(", ")}`}</title>
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
