import { describe, expect, it } from "vitest";
import { findExternalUrls } from "./url-check.mjs";

describe("findExternalUrls", () => {
  it.each([
    'fetch("http://localhost.evil.com/x")',
    'a="http://127.0.0.1.evil.com/a"',
    'import("//cdn.example.com/x.js")',
    'src="//cdn.example.com/x.js"',
    "url(https://fonts.googleapis.com/css)",
  ])("flags %s", (s) => expect(findExternalUrls(s).length).toBeGreaterThan(0));

  it.each([
    'fetch("http://localhost:8600/api")',
    'x="http://127.0.0.1:8600"',
    'ns="http://www.w3.org/2000/svg"',
    "// a comment about foo.bar",
    "const re=/a\\/\\/b.c/;",
    'fetch("/api/v1/health")',
  ])("allows %s", (s) => expect(findExternalUrls(s)).toEqual([]));
});
