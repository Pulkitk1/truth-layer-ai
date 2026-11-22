"""Checks that a corrected figure proposed by the AI really appears in the evidence it cites.

The model is never trusted to produce a number from memory: a corrected value is kept only when a cited source
contains that figure (numbers are compared by value, so "1.43 billion" matches "1,428,627,663")."""
import re

_SCALES = {
    "thousand": 1e3, "k": 1e3, "lakh": 1e5, "lakhs": 1e5, "million": 1e6, "mn": 1e6, "m": 1e6, "mm": 1e6,
    "crore": 1e7, "crores": 1e7, "billion": 1e9, "bn": 1e9, "b": 1e9, "trillion": 1e12, "tn": 1e12, "t": 1e12,
}
_NUM = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(%|percent\b|per cent\b|[a-zA-Z]{1,9}\b))?"
)
YEAR_RE = re.compile(r"^(1[5-9]\d\d|20\d\d)$")


def numbers_in(text: str) -> list[tuple[float, bool]]:
    """All numbers in text as (value, is_plain_integer_without_scale). Scale words multiply the value."""
    out: list[tuple[float, bool]] = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        word = (m.group(2) or "").lower()
        scale = _SCALES.get(word)
        if scale:
            out.append((value * scale, False))
        else:
            out.append((value, "." not in raw and not word))
        if scale:  # also keep the bare number: "1.4 billion" may be written "1.4" next to a column header
            out.append((value, False))
    return out


def _close(a: float, b: float) -> bool:
    if a == b:
        return True
    return a != 0 and abs(a - b) / abs(a) <= 0.03


def grounded(corrected: str | None, evidence_texts: list[str]) -> bool:
    """True when the corrected value is present in at least one of the evidence texts."""
    if not corrected or not corrected.strip():
        return False
    corpus = " ".join(evidence_texts)
    wanted = numbers_in(corrected)
    if not wanted:  # a non-numeric correction (a name, a place): the text itself must appear
        return corrected.strip().lower() in corpus.lower()
    have = numbers_in(corpus)
    # the first number is the figure itself; later numbers are usually years/periods, so only the figure is required
    value, _ = wanted[0]
    if YEAR_RE.match(str(int(value))) and value == int(value):
        return any(v == value for v, _ in have)  # years and dates must match exactly
    # "1.46 billion" is also accepted when the source prints "1.46" under a "billion" column header
    candidates = [value] + [v for v, _ in wanted[1:2] if v < value]
    return any(_close(c, v) for c in candidates for v, _ in have)
