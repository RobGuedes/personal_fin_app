import { parseAmount } from "./parse";

describe("parseAmount", () => {
  it.each([
    ["1.234,56", 1234.56], ["-1.234,56", -1234.56], ["1234,56", 1234.56], ["1234.56", 1234.56], ["-20.5", -20.5],
    ["1.500", 1500], ["1.234.567", 1234567], ["0.500", 0.5], ["1500", 1500], ["−300", -300], ["0,5", 0.5], ["  12 ", 12],
  ])("%s -> %s", (text, expected) => expect(parseAmount(text)).toBe(expected));

  it.each(["1,234.56", "1.23,4", "12.34.567,89", "abc", "", "1,2,3", "1.234,5x"])("%s -> NaN", (text) => expect(parseAmount(text)).toBeNaN());
});
