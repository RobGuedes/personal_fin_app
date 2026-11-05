import css from "./tokens.css?raw";

function decls(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.replace(/\/\*.*?\*\//gs, "").matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

/** Declarations of every dark block, merged: the media-query ones (system dark) and the [data-theme="dark"] ones. */
function darkBlocks() {
  const media: Record<string, string> = {};
  const attr: Record<string, string> = {};
  for (const m of css.matchAll(/@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{([^}]*)\}/g)) Object.assign(media, decls(m[1]));
  for (const m of css.matchAll(/:root\[data-theme="dark"\] \{([^}]*)\}/g)) Object.assign(attr, decls(m[1]));
  return { media, attr };
}

describe("tokens.css dark parity", () => {
  it("the system-dark block and [data-theme=dark] declare identical tokens", () => {
    const { media, attr } = darkBlocks();
    expect(Object.keys(media).length).toBeGreaterThan(20);
    expect(attr).toEqual(media);
  });

  it("has the same number of blocks on both sides", () => {
    expect((css.match(/prefers-color-scheme: dark/g) ?? []).length).toBe((css.match(/:root\[data-theme="dark"\]/g) ?? []).length);
  });
});

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("server banner contrast (WCAG AA text, 4.5:1)", () => {
  const light = decls(css.match(/:root\s*\{([^}]*)\}/)![1]);
  const { media, attr } = darkBlocks();
  it.each([["light", light], ["dark (system)", media], ["dark (manual)", attr]] as const)("%s", (_name, tokens) => {
    expect(tokens["--banner-bg"]).toBeTruthy();
    expect(contrast(tokens["--banner-ink"], tokens["--banner-bg"])).toBeGreaterThanOrEqual(4.5);
  });
});
