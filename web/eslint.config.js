// Types are checked by `tsc -b`; ESLint adds the TypeScript and React Hooks rule sets
// (rules-of-hooks, exhaustive-deps) over the app source, and plain rules over scripts/config.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src/api/schema.d.ts"] },
  { files: ["**/*.{js,mjs}"], extends: [js.configs.recommended], languageOptions: { globals: globals.node } },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: { "react-hooks": reactHooks },
    languageOptions: { globals: globals.browser },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test-setup.ts"],
    languageOptions: { globals: { ...globals.browser, ...globals.node, vi: "readonly", describe: "readonly",
      it: "readonly", expect: "readonly", beforeEach: "readonly", afterEach: "readonly", beforeAll: "readonly",
      afterAll: "readonly" } },
    rules: { "@typescript-eslint/no-non-null-assertion": "off" },
  },
);
