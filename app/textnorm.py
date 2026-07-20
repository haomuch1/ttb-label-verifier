"""Text normalization helpers for the rules engine.

The balance that matters most here: the health-warning comparison must
survive line wrapping and hyphenation as printed on real labels (Lenz
Moser breaks "ALCOHOLIC BEV- / ERAGES" across lines), but must NOT
normalize case — case sensitivity is what catches a title-case
"Government Warning:" violation.
"""

import re

# Unicode punctuation that extraction may return for what the label prints
# as plain ASCII. Mapping these is an OCR-artifact fix, not a compliance
# judgment: a curly apostrophe is not a labeling violation.
_UNICODE_PUNCT = {
    "‘": "'",   # left single quote
    "’": "'",   # right single quote / apostrophe
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "–": "-",   # en dash
    "—": "-",   # em dash
    "­": "-",   # soft hyphen
    " ": " ",   # non-breaking space
}


def normalize_punctuation(text: str) -> str:
    for src, dst in _UNICODE_PUNCT.items():
        text = text.replace(src, dst)
    return text


def rejoin_hyphenated_breaks(text: str) -> str:
    """Rejoin a word hyphenated across a line break.

    "ALCOHOLIC BEV-\\nERAGES" -> "ALCOHOLIC BEVERAGES". Only fires on a
    hyphen at end-of-line followed by a word character, so legitimate
    hyphens inside a line are untouched. Safe for the health warning:
    the statutory text contains no hyphenated words.
    """
    return re.sub(r"(\w)-[ \t]*\n\s*(\w)", r"\1\2", text)


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_warning(text: str) -> str:
    """Prepare verbatim warning text for the strict comparison.

    Rejoins hyphenated line breaks and collapses whitespace. Case is
    deliberately preserved.
    """
    return collapse_whitespace(rejoin_hyphenated_breaks(normalize_punctuation(text)))


def normalize_loose(text: str) -> str:
    """Case- and punctuation-insensitive form for fuzzy cross-checks.

    "STONE'S THROW" and "Stone's Throw" normalize identically. Apostrophes
    are deleted (STONE'S == Stones); other punctuation becomes a space
    (Stone-Throw == Stone Throw). Accented letters are kept so
    "Bärenjäger" survives.
    """
    text = normalize_punctuation(text).casefold()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    text = text.replace("_", " ")
    return collapse_whitespace(text)


_PCT_NUMBER = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_BARE_NUMBER = re.compile(r"(\d{1,3}(?:\.\d+)?)")


def parse_abv(raw: str | None) -> float | None:
    """Parse an alcohol-content statement into a percentage.

    Real filings vary: Bärenjäger's form says just "35", Lenz Moser's says
    "12%", labels say "39% ALC / VOL" or "ALC. 35% BY VOL." A number
    adjacent to '%' wins over a bare number. Returns None if nothing
    plausible (0 < abv <= 100) is found.
    """
    if not raw:
        return None
    m = _PCT_NUMBER.search(raw) or _BARE_NUMBER.search(raw)
    if not m:
        return None
    value = float(m.group(1))
    return value if 0 < value <= 100 else None


# Net contents: normalize notation and metric scale, but keep measurement
# systems apart. Metric quantities canonicalize to milliliters; US fluid
# ounces stay in their own system — converting across systems would
# silently answer a real standards-of-fill question that belongs to a
# human.
_NET_UNITS: list[tuple[str, str, float]] = [
    # (regex fragment, system, factor to canonical unit of that system)
    (r"millilit(?:er|re)s?", "metric", 1),
    (r"centilit(?:er|re)s?", "metric", 10),
    (r"lit(?:er|re)s?", "metric", 1000),
    (r"ml", "metric", 1),
    (r"cl", "metric", 10),
    (r"l", "metric", 1000),
    (r"fluid\s+ounces?", "fl oz", 1),
    (r"fl\.?\s*ozs?\.?", "fl oz", 1),
    (r"ounces?", "fl oz", 1),
    (r"oz\.?", "fl oz", 1),
]

_NET_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + "|".join(u for u, _, _ in _NET_UNITS) + r")\b",
    re.IGNORECASE,
)


def parse_net_contents(raw: str | None) -> tuple[float, str] | None:
    """Parse a net-contents statement into (quantity, system).

    Metric returns milliliters ("750 MILLILITERS", "750ml", "75 cl", and
    "0.75 L" all parse to (750.0, "metric")); US fluid ounces return
    (value, "fl oz"). None when nothing parseable is found.
    """
    if not raw:
        return None
    m = _NET_RE.search(raw)
    if not m:
        return None
    value, unit_text = float(m.group(1)), m.group(2)
    for fragment, system, factor in _NET_UNITS:
        if re.fullmatch(fragment, unit_text, re.IGNORECASE):
            return value * factor, system
    return None


def parse_proof(raw: str | None) -> float | None:
    """Parse a proof statement ("70 PROOF", or a bare "70")."""
    if not raw:
        return None
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:°\s*)?proof", raw, re.IGNORECASE)
    if not m:
        m = _BARE_NUMBER.search(raw)
    if not m:
        return None
    value = float(m.group(1))
    return value if 0 < value <= 200 else None
