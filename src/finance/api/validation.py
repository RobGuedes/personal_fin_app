"""Shared input bounds for request bodies (pt-BR errors). Checked before anything is written."""

import math
import unicodedata

from finance.api.errors import ApiError

MAX_AMOUNT = 100_000_000.0  # R$ 100 mi: far above any real entry, far below float trouble
NOTE_MAX = 500
_ALLOWED_CONTROLS = {"\n", "\t"}


def check_amount(value: float, *, positive: bool, code: str = "invalid_amount", message: str) -> float:
    """Finite, non-zero, |value| <= MAX_AMOUNT (and > 0 if `positive`). Returns it rounded to cents."""
    if not math.isfinite(value) or value == 0 or abs(value) > MAX_AMOUNT or (positive and value < 0):
        raise ApiError(422, code, message)
    return round(value, 2)


def clean_note(note: str | None) -> str:
    """Strip; at most NOTE_MAX chars; no control characters (except newline/tab) or lone surrogates."""
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise ApiError(422, "note_too_long", f"A descrição deve ter no máximo {NOTE_MAX} caracteres.")
    try:
        note.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(422, "invalid_note", "A descrição contém caracteres inválidos.") from None
    if any(unicodedata.category(c) == "Cc" and c not in _ALLOWED_CONTROLS for c in note):
        raise ApiError(422, "invalid_note", "A descrição contém caracteres inválidos.")
    return note
