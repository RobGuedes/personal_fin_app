// Writes src/api/schema.d.ts from the FastAPI OpenAPI schema. create_app() serves no
// /openapi.json, so the schema is dumped straight from the app object (no server needed).
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const root = new URL("../..", import.meta.url).pathname;
const json = execFileSync(
  "uv",
  ["run", "python", "-c", "import json; from finance.api import create_app; print(json.dumps(create_app().openapi()))"],
  { cwd: root, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
);
const tmp = join(mkdtempSync(join(tmpdir(), "openapi-")), "openapi.json");
writeFileSync(tmp, json);
execFileSync("npx", ["openapi-typescript", tmp, "-o", "src/api/schema.d.ts"], {
  cwd: new URL("..", import.meta.url).pathname,
  stdio: "inherit",
});
