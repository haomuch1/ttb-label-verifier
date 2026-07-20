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
