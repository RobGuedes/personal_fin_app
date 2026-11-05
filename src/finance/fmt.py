"""Display formatting for the CLI: BRL money (the web app formats in web/src/lib/format.ts)."""

def brl(value: float | None) -> str:
    """1234.5 -> 'R$ 1.234,50'; -1234.5 -> '-R$ 1.234,50'."""
    if value is None:
        return ""
    s = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if value < -0.005 else f"R$ {s}"
