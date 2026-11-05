// Pure helper for check-no-external-urls.mjs (unit-tested in url-check.test.mjs).
const ALLOWED = [
  /^https?:\/\/www\.w3\.org\//, // SVG / XML namespaces
  /^https?:\/\/reactjs\.org\/docs\/error-decoder/, // React error text (never fetched)
  /^https?:\/\/react\.dev\//,
  /^https?:\/\/reactrouter\.com\//, // react-router dev-warning text (never fetched)
  /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$|[`'"])/,
];

// Absolute URLs, plus protocol-relative "//host.tld" appearing right after a quote, backtick,
// "(" "=" "," or whitespace. Requires a dotted host with no space after "//", so line comments
// ("// note"), regex literals ("\/\/") and "://" inside absolute URLs are not matched.
const ABSOLUTE = /https?:\/\/[^\s"'`)\\<>]+/g;
const PROTO_RELATIVE = /(?<=["'`(=,\s])\/\/[a-z0-9-]+(?:\.[a-z0-9-]+)+[^\s"'`)\\<>]*/gi;

/** Returns the external URLs found in `text` (empty = clean). */
export function findExternalUrls(text) {
  const bad = [];
  for (const m of text.matchAll(ABSOLUTE)) if (!ALLOWED.some((re) => re.test(m[0]))) bad.push(m[0]);
  for (const m of text.matchAll(PROTO_RELATIVE)) bad.push(m[0]);
  return bad;
}
