// Fails the build if the bundle references any external origin (the app only talks to same-origin /api).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { findExternalUrls } from "./url-check.mjs";

const dist = new URL("../dist", import.meta.url).pathname;
const bad = [];
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(js|css|html|svg|json|webmanifest)$/.test(name)) {
      for (const url of findExternalUrls(readFileSync(p, "utf8"))) bad.push(`${p.replace(dist, "dist")}: ${url}`);
    }
  }
}
walk(dist);
if (bad.length) {
  console.error("External URLs found in build output:\n" + [...new Set(bad)].join("\n"));
  process.exit(1);
}
console.log("check-no-external-urls: ok");
