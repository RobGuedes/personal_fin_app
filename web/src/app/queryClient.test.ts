import { ApiError } from "../api/client";
import { shouldRetry } from "./queryClient";

describe("query retry policy", () => {
  it("never retries a 4xx (not found, invalid input): the error shows at once", () => {
    expect(shouldRetry(0, new ApiError(404, "Categoria não encontrada"))).toBe(false);
    expect(shouldRetry(0, new ApiError(422, "Mês inválido"))).toBe(false);
  });

  it("retries a 5xx or a network failure, at most twice", () => {
    expect(shouldRetry(0, new ApiError(500, "x"))).toBe(true);
    expect(shouldRetry(1, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetry(2, new ApiError(503, "x"))).toBe(false);
  });
});
