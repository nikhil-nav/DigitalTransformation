"""Field-specific parsers for Epic 3 (US 3.2 last bullet).

Each parser takes a raw cell value and returns ``ParseResult(value, ok)``.
On success the value is the canonical normalised form (E.164 for phone,
lowercase RFC-5322 for email, ISO-8601 for date). On failure the value is
the original input, preserved exactly so callers can show it to the user.

Precision commitments:
- We NEVER silently drop a failing parse. The caller is given ``ok=False``
  and decides whether to compare the raw value, annotate the row as
  "unparseable", or skip the column for that pair.
- Phone parser uses libphonenumber via the ``phonenumbers`` package. We do
  not invent a default country; if no leading "+" and no region hint is
  given we treat the parse as failed.  Adding country inference later is a
  config-page decision, not a parser default.
- Date parser uses ``dateparser`` (Settings: STRICT_PARSING=True) so
  freeform language like "next Tuesday" does NOT parse, only concrete date
  strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import dateparser
import phonenumbers

from app.data_quality.normalize import _is_nullish

PARSERS_VERSION = "1.0.0"


@dataclass(frozen=True)
class ParseResult:
    value: str
    ok: bool


def _raw_str(value: Any) -> str:
    if _is_nullish(value):
        return ""
    return str(value).strip()


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------


def parse_phone_e164(value: Any, *, default_region: str | None = None) -> ParseResult:
    """Parse a phone number into E.164 (e.g. "+14155550142").

    ``default_region`` (ISO-3166 alpha-2) is required for inputs without a
    leading "+". When omitted, regionless inputs fail parsing rather than
    being silently associated with an arbitrary country.

    Examples (all parse to "+14155550142" given default_region="US"):
        "(415) 555-0142"
        "415-555-0142"
        "4155550142"
        "415.555.0142"
        "+1 415 555 0142"
    """
    raw = _raw_str(value)
    if not raw:
        return ParseResult(value=str(value) if value is not None else "", ok=False)
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return ParseResult(value=raw, ok=False)
    if not phonenumbers.is_valid_number(parsed):
        return ParseResult(value=raw, ok=False)
    return ParseResult(
        value=phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        ok=True,
    )


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

# Pragmatic RFC-5322 subset: at least one char before @, a domain with a dot.
# We DO NOT validate the full RFC because it would accept many forms that
# break downstream systems; this is the same conservative shape used by the
# Part 1 pattern catalogue.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)


def parse_email(value: Any) -> ParseResult:
    """Lowercase + trim. The local-part of an email is technically
    case-sensitive per RFC, but virtually every real-world system treats it
    as case-insensitive; we standardise on lowercase for matching."""
    raw = _raw_str(value)
    if not raw:
        return ParseResult(value=str(value) if value is not None else "", ok=False)
    candidate = raw.lower()
    if not _EMAIL_RE.match(candidate):
        return ParseResult(value=raw, ok=False)
    return ParseResult(value=candidate, ok=True)


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

_DATEPARSER_SETTINGS = {
    # STRICT_PARSING requires that all date components be present (no
    # silent year=current-year inference).
    "STRICT_PARSING": True,
    # PARSERS limits dateparser to absolute-time forms only; without this,
    # "yesterday" / "next Tuesday" would resolve relative to today and
    # produce a non-reproducible result.
    "PARSERS": ["absolute-time"],
    # The default returns naive datetimes; we only care about the date part.
    "RETURN_AS_TIMEZONE_AWARE": False,
}


def parse_date_iso(value: Any) -> ParseResult:
    """Parse a date in any common format to ISO-8601 ("YYYY-MM-DD").

    Time components are intentionally discarded — record-linkage on dates
    rarely needs sub-day precision, and including time risks false
    mismatches when one source stamps "00:00:00" and another doesn't.
    """
    raw = _raw_str(value)
    if not raw:
        return ParseResult(value=str(value) if value is not None else "", ok=False)
    parsed = dateparser.parse(raw, settings=_DATEPARSER_SETTINGS)
    if parsed is None:
        return ParseResult(value=raw, ok=False)
    return ParseResult(value=parsed.date().isoformat(), ok=True)


PARSERS = {
    "phone": parse_phone_e164,
    "email": parse_email,
    "date": parse_date_iso,
}
