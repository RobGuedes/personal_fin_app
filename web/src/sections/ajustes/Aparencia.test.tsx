import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Aparencia } from "./Aparencia";
import { applyStoredTheme } from "../../theme/theme";

describe("Aparência", () => {
  beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });

  it("defaults to Sistema (no attribute) and offers three choices", () => {
    render(<Aparencia />);
    expect((screen.getByRole("radio", { name: "Sistema" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("Escuro and Claro set data-theme and persist; Sistema removes it", async () => {
    render(<Aparencia />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Escuro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("finance-theme")).toBe("dark");
    await user.click(screen.getByRole("radio", { name: "Claro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    await user.click(screen.getByRole("radio", { name: "Sistema" }));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem("finance-theme")).toBe("system");
  });

  it("applies the stored choice on start and ignores junk", () => {
    localStorage.setItem("finance-theme", "dark");
    applyStoredTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    localStorage.setItem("finance-theme", "neon");
    applyStoredTheme();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("shows the stored choice as selected", () => {
    localStorage.setItem("finance-theme", "light");
    render(<Aparencia />);
    expect((screen.getByRole("radio", { name: "Claro" }) as HTMLInputElement).checked).toBe(true);
  });
});
