import { amountSigned, brl, brlCompact, brlK, brlSigned, dateBR, dayHeader, dayLabel, monthLabel, pct } from "./format";

describe("format", () => {
  it("brl", () => {
    expect(brl(1234.56)).toBe("R$ 1.234,56");
    expect(brl(-12)).toBe("−R$ 12,00");
    expect(brl(0)).toBe("R$ 0,00");
  });
  it("brlK: signed thousands with one decimal, bare 0 when it rounds to zero", () => {
    expect(brlK(28400)).toBe("+28,4k");
    expect(brlK(-6200)).toBe("−6,2k");
    expect(brlK(31234.56)).toBe("+31,2k");
    expect(brlK(1132.29)).toBe("+1,1k");
    expect(brlK(123456.78)).toBe("+123,5k");
    expect(brlK(-0)).toBe("0");
    expect(brlK(-40)).toBe("0");
    expect(brlK(60)).toBe("+0,1k");
  });

  it("brlCompact", () => {
    expect(brlCompact(54900)).toBe("R$ 54,9 mil");
    expect(brlCompact(1240000)).toBe("R$ 1,24 mi");
    expect(brlCompact(950)).toBe("R$ 950");
    expect(brlCompact(-54900)).toBe("−R$ 54,9 mil");
  });
  it("dates", () => {
    expect(dateBR("2026-10-24")).toBe("24/10/2026");
  });

  it("a timestamp shows its São Paulo day, not its UTC day (sync at 22:39 local = 01:39Z next day)", () => {
    expect(dateBR("2026-11-03T01:39:58+00:00")).toBe("02/11/2026");
    expect(dateBR("2026-10-30T12:00:00Z")).toBe("30/10/2026");
    expect(dateBR("2026-11-01T02:59:59.000Z")).toBe("31/10/2026"); // month boundary
    expect(dayLabel("2026-10-23")).toBe("sex, 23 out");
    expect(monthLabel("2026-10")).toBe("Outubro");
  });
  it("pct", () => {
    expect(pct(0.384)).toBe("38%");
  });
});

describe("format edge cases", () => {
  it("brlCompact rounds before choosing the unit", () => {
    expect(brlCompact(999_999)).toBe("R$ 1,00 mi");
    expect(brlCompact(999_950)).toBe("R$ 1,00 mi");
    expect(brlCompact(999)).toBe("R$ 999");
    expect(brlCompact(999.6)).toBe("R$ 1 mil");
  });
  it("never shows a minus for values that round to zero", () => {
    expect(brlCompact(-0.2)).toBe("R$ 0");
    expect(brlCompact(-0)).toBe("R$ 0");
    expect(brl(-0.004)).toBe("R$ 0,00");
  });
});

import { brlInt, monthShort, shiftMonth } from "./format";

describe("format (Início helpers)", () => {
  it("brlInt", () => {
    expect(brlInt(20600.4)).toBe("R$ 20.600");
    expect(brlInt(-1500)).toBe("−R$ 1.500");
    expect(brlInt(-0.2)).toBe("R$ 0");
  });
  it("months", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2025-12", 1)).toBe("2026-01");
    expect(monthShort("2026-10")).toBe("out");
  });
});

describe("transaction list formats", () => {
  it("dayHeader: today, this month, other months and years", () => {
    expect(dayHeader("2026-10-24", "2026-10-24")).toBe("HOJE · SÁB 24");
    expect(dayHeader("2026-10-23", "2026-10-24")).toBe("SEX 23");
    expect(dayHeader("2026-09-30", "2026-10-24")).toBe("QUA 30 SET");
    expect(dayHeader("2025-12-05", "2026-10-24")).toBe("SEX 5 DEZ 2025");
  });
  it("signed amounts with a spaced sign", () => {
    expect(brlSigned(8123.4)).toBe("+ R$ 8.123,40");
    expect(brlSigned(-312.4)).toBe("− R$ 312,40");
    expect(brlSigned(0)).toBe("R$ 0,00");
    expect(amountSigned(-218.9)).toBe("− 218,90");
    expect(amountSigned(8640)).toBe("+ 8.640,00");
    expect(amountSigned(-5000, false)).toBe("5.000,00");
  });
});
