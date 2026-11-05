import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./Toast";

function Trigger() {
  const toast = useToast();
  return <button onClick={() => toast.show("Salvo")}>go</button>;
}

describe("Toast timers", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("auto-dismisses after the duration", async () => {
    render(<ToastProvider durationMs={1000}><Trigger /></ToastProvider>);
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(screen.getByText("go"));
    expect(screen.getByText("Salvo")).toBeTruthy();
    act(() => vi.advanceTimersByTime(1100));
    expect(screen.queryByText("Salvo")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the pending timer when dismissed by hand", async () => {
    render(<ToastProvider durationMs={60000}><Trigger /></ToastProvider>);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByText("go"));
    const before = vi.getTimerCount();
    await user.click(screen.getByRole("button", { name: "Fechar" }));
    expect(screen.queryByText("Salvo")).toBeNull();
    expect(vi.getTimerCount()).toBeLessThan(before);
  });

  it("clears pending timers on unmount: no state update afterwards", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<ToastProvider durationMs={60000}><Trigger /></ToastProvider>);
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(screen.getByText("go"));
    const during = vi.getTimerCount();
    unmount();
    expect(vi.getTimerCount()).toBeLessThan(during);
    act(() => vi.advanceTimersByTime(61000));
    expect(err).not.toHaveBeenCalled();
    err.mockRestore();
  });
});
