export type ThemeChoice = "light" | "dark" | "system";

export const THEME_KEY = "finance-theme";
const CHOICES: readonly ThemeChoice[] = ["light", "dark", "system"];

export function getStoredTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return CHOICES.includes(v as ThemeChoice) ? (v as ThemeChoice) : "system";
  } catch {
    return "system";
  }
}

/** "Sistema" = no attribute: prefers-color-scheme drives the tokens. */
export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function setTheme(choice: ThemeChoice): void {
  try {
    localStorage.setItem(THEME_KEY, choice);
  } catch {
    /* private mode: the choice lasts for this visit */
  }
  applyTheme(choice);
}

/** Called from main.tsx before the first render. */
export function applyStoredTheme(): void {
  applyTheme(getStoredTheme());
}
