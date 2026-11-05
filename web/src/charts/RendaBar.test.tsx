import { render, screen } from "@testing-library/react";
import { RendaBar } from "./RendaBar";

const ok = { renda: 54900, despesas: 30750, outros: 3550, sobrou: 20600, scale: 54900, deficit: false };
const deficit = { renda: 10000, despesas: 10500, outros: 1000, sobrou: -1500, scale: 11500, deficit: true };

describe("RendaBar", () => {
  it("legend shows names and % of renda", () => {
    render(<RendaBar split={ok} />);
    for (const s of ["Despesas 56%", "Outros 6%", "Sobrou 38%"]) expect(screen.getByText(s)).toBeTruthy();
    expect(screen.queryByTestId("income-marker")).toBeNull();
  });

  it("deficit: marker where income ended and a Faltou legend", () => {
    render(<RendaBar split={deficit} />);
    const marker = screen.getByTestId("income-marker");
    expect(marker.style.left).toBe(`${(10000 / 11500) * 100}%`);
    expect(screen.getByText("Faltou 15%")).toBeTruthy();
    expect(screen.queryByText(/^Sobrou/)).toBeNull();
  });
});
