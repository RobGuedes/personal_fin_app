import { QueryClient } from "@tanstack/react-query";
import { invalidateAfterMutation } from "./queries";

describe("invalidateAfterMutation", () => {
  it("invalidates every query a classification change can move, Ajustes lists included", async () => {
    const qc = new QueryClient();
    const keys = ["summary", "panorama", "transactions", "review", "taxonomy", "rules", "transfers", "manualEntries", "budgets"];
    for (const k of keys) qc.setQueryData([k], { seeded: true });
    await invalidateAfterMutation(qc);
    expect(keys.filter((k) => !qc.getQueryState([k])?.isInvalidated)).toEqual([]);
  });
});
