"""Phase 7 Batch 7J2 — flexible list-search matching (approved 7J1 Final
contract, Sections 4.1-4.10; D-1..D-11).

One pure rule, with no I/O, shared by the vehicle and equipment list
services for both repositories. It only decides whether a record matches a
query: stored values, identities, ordering and paging are never changed.

- The query is split on whitespace (`str.isspace`, D-3) into tokens, lower-
  cased with `str.lower`; duplicates collapse; hyphen-only tokens are
  dropped (D-2: U+002D only). Every remaining token must match the same
  record (D-1: each token may match a different field).
- A token matches when it is a substring of any eligible field (literal),
  or — for identifier fields only — when it is a substring after
  whitespace and U+002D are removed from both sides, or (D-11) when it is a
  Thai/ASCII-digit token whose pieces all occur in ONE name field.
- No numeric conversion, Unicode normalization, Thai-digit equivalence,
  fuzzy matching, synonyms or ranking (D-5).
"""
from __future__ import annotations

from collections.abc import Sequence

HYPHEN = "-"  # U+002D HYPHEN-MINUS only (D-2)

# D-11 character classes (7J1 Final 4.10).
_THAI_LETTER_RANGES = ((0x0E01, 0x0E3A), (0x0E40, 0x0E4E))
_THAI_COMBINING = frozenset({0x0E31, *range(0x0E34, 0x0E3B), *range(0x0E47, 0x0E4F)})


def _is_thai_letter(ch: str) -> bool:
    """Thai consonants, vowels, tone and other combining marks. Excludes the
    Baht sign U+0E3F, fongman U+0E4F, Thai digits U+0E50-U+0E59 and
    U+0E5A-U+0E5B."""
    code = ord(ch)
    return any(low <= code <= high for low, high in _THAI_LETTER_RANGES)


def _is_thai_base(ch: str) -> bool:
    return _is_thai_letter(ch) and ord(ch) not in _THAI_COMBINING


def _is_ascii_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def tokenize(q: str | None) -> tuple[str, ...] | None:
    """None when there is no text filter (None, empty or whitespace-only q).
    Otherwise the usable tokens; an EMPTY tuple means the query contained
    only hyphen-only tokens and matches nothing (D-4)."""
    if q is None or not q.strip():
        return None
    tokens: list[str] = []
    for raw in q.split():
        token = raw.lower()
        if not token.strip(HYPHEN):
            continue
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def compact(value: str) -> str:
    """Lower-cased value without whitespace and U+002D — used only to compare
    identifiers inside the match predicate, never stored or returned."""
    return "".join(ch for ch in value.lower() if not ch.isspace() and ch != HYPHEN)


def thai_digit_pieces(token: str) -> tuple[str, ...] | None:
    """D-11: the maximal Thai-letter / ASCII-digit runs of an eligible token,
    deduplicated in order, or None when the token is not eligible (it then
    matches only through the literal and identifier rules)."""
    if not token or not all(_is_thai_letter(ch) or _is_ascii_digit(ch) for ch in token):
        return None
    if not any(_is_thai_letter(ch) for ch in token) or not any(_is_ascii_digit(ch) for ch in token):
        return None
    pieces: list[str] = []
    current = token[0]
    for previous, ch in zip(token, token[1:]):
        if _is_ascii_digit(previous) == _is_ascii_digit(ch):
            current += ch
        else:
            pieces.append(current)
            current = ch
    pieces.append(current)
    # A Thai run consisting only of combining marks makes the token ineligible.
    for piece in pieces:
        if not _is_ascii_digit(piece[0]) and not any(_is_thai_base(ch) for ch in piece):
            return None
    return tuple(dict.fromkeys(pieces))


def token_matches(
    token: str, name_fields: Sequence[str], identifier_fields: Sequence[str]
) -> bool:
    """One ORIGINAL query token against one record's fields: literal OR
    identifier-compact OR (D-11) all pieces inside ONE name field."""
    for field in (*name_fields, *identifier_fields):
        if field and token in field.lower():
            return True
    compact_token = compact(token)
    if compact_token:
        for field in identifier_fields:
            if field and compact_token in compact(field):
                return True
    pieces = thai_digit_pieces(token)
    if pieces:
        for field in name_fields:
            if field:
                lowered = field.lower()
                if all(piece in lowered for piece in pieces):
                    return True
    return False


def record_matches(
    tokens: tuple[str, ...] | None,
    name_fields: Sequence[str],
    identifier_fields: Sequence[str],
) -> bool:
    """True when every token matches some field of this record (D-1). None
    tokens = no text filter; an empty tuple matches nothing (D-4)."""
    if tokens is None:
        return True
    if not tokens:
        return False
    return all(token_matches(token, name_fields, identifier_fields) for token in tokens)
