import { useState } from "react";
import { Card } from "../../components/Card";
import { t } from "../../i18n/pt-BR";
import { getStoredTheme, setTheme, type ThemeChoice } from "../../theme/theme";

const OPTIONS: { id: ThemeChoice; label: string }[] = [
  { id: "light", label: t.settings.appearance.light },
  { id: "dark", label: t.settings.appearance.dark },
  { id: "system", label: t.settings.appearance.system },
];

export function Aparencia() {
  const [choice, setChoice] = useState<ThemeChoice>(getStoredTheme);
  return (
    <Card title={<h2 className="aj-h">{t.settings.appearance.title}</h2>}>
      <div role="radiogroup" aria-label={t.settings.appearance.group} className="aj-seg">
        {OPTIONS.map((o) => (
          <label key={o.id} className={choice === o.id ? "sel" : ""}>
            <input
              type="radio"
              name="theme"
              checked={choice === o.id}
              onChange={() => {
                setTheme(o.id);
                setChoice(o.id);
              }}
            />
            {o.label}
          </label>
        ))}
      </div>
    </Card>
  );
}
