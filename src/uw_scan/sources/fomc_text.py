"""Strict extraction helpers for official FOMC statement text."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from uw_scan.normalize import NormalizationError

logger = logging.getLogger(__name__)

_HYPHENS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
_FRACTIONS = str.maketrans(
    {
        "¼": "1/4",
        "½": "1/2",
        "¾": "3/4",
        "⅛": "1/8",
        "⅜": "3/8",
        "⅝": "5/8",
        "⅞": "7/8",
        "⁄": "/",
    }
)
_NUMERIC_TOKEN = r"(?:\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_TARGET_RANGE = (
    rf"(?P<lower>{_NUMERIC_TOKEN})\s+to\s+"
    rf"(?P<upper>{_NUMERIC_TOKEN})\s+percent"
)
_DECISION_PATTERNS = (
    re.compile(
        rf"\bthe (?:federal open market committee|committee) decided(?: today)? to "
        rf"(?P<verb>maintain|keep|raise|increase|lower) "
        rf"the target range for the federal funds rate "
        rf"(?:(?:at|to)\s+|by\s+{_NUMERIC_TOKEN}\s+percentage points?,?\s+to\s+)"
        rf"{_TARGET_RANGE}",
    ),
    re.compile(
        rf"\bthe federal open market committee directs the desk to undertake "
        rf"open market operations as necessary to (?P<verb>maintain|keep) "
        rf"the federal funds rate in a target range of {_TARGET_RANGE}",
    ),
)
_VOTER_NAME = re.compile(
    r"[A-Z][A-Za-z'’-]*"
    r"(?:\s+(?:[A-Z]\.|[A-Z][A-Za-z'’-]*)){1,4}"
    r"(?:,\s*(?:Chair|Vice Chair))?"
)
_FOR_PREFIX = "Voting for the monetary policy action were "
_NOTATION_PREFIX = "Voting (by notation) for the monetary policy action were "
_AGAINST_PREFIX = re.compile(r"Voting against (?:this action|the action) (?:was|were) ")
_ALTERNATE_ACTOR = (
    r"(?:(?:Mr|Ms|Mrs)\.\s+[A-Z][A-Za-z'’-]+|"
    r"[A-Z][A-Za-z'’-]*(?:\s+(?:[A-Z]\.|[A-Z][A-Za-z'’-]*)){1,4})"
)
_ALTERNATE_SUFFIX = re.compile(
    rf"\.\s+{_ALTERNATE_ACTOR} voted as an alternate member at this meeting\.$"
)


def _normalize_policy_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.translate(_HYPHENS).translate(_FRACTIONS)
    return " ".join(normalized.split())


def _normalized_html_text(html: str) -> str:
    return _normalize_policy_text(BeautifulSoup(html, "html.parser").get_text(" "))


def _normalized_paragraphs(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    paragraphs: list[str] = []
    for paragraph in soup.find_all("p"):
        normalized = _normalize_policy_text(paragraph.get_text(" "))
        if normalized:
            paragraphs.append(normalized)
    return paragraphs or [_normalized_html_text(html)]


def _infer_action(html: str) -> str | None:
    decision = _extract_policy_decision(html)
    if decision is None:
        return None
    verb = decision[0]
    if verb in {"maintain", "keep"}:
        return "Hold"
    if verb in {"raise", "increase"}:
        return "Hike"
    return "Cut"


def _infer_target_range(html: str) -> tuple[Decimal, Decimal] | None:
    compact = _normalized_html_text(html).lower()
    decision = _extract_policy_decision(html)
    if decision is not None:
        lower_raw, upper_raw = decision[1], decision[2]
    else:
        direct = re.fullmatch(_TARGET_RANGE, compact)
        if direct is None:
            return None
        lower_raw, upper_raw = direct.group("lower"), direct.group("upper")
    try:
        lower = _parse_numeric_token(lower_raw)
        upper = _parse_numeric_token(upper_raw)
        if lower > upper:
            raise ValueError("FOMC target range lower bound exceeds upper bound")
        return lower, upper
    except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
        logger.debug("invalid FOMC target range: %s", repr(exc))
        return None


def _extract_policy_decision(html: str) -> tuple[str, str, str] | None:
    decisions: list[tuple[str, str, str]] = []
    for paragraph in _normalized_paragraphs(html):
        lowered = paragraph.lower()
        for pattern in _DECISION_PATTERNS:
            decisions.extend(
                (match.group("verb"), match.group("lower"), match.group("upper"))
                for match in pattern.finditer(lowered)
            )
    if len(decisions) > 1:
        raise NormalizationError("FOMC statement contains multiple policy decisions")
    return decisions[0] if decisions else None


def _parse_numeric_token(raw: str) -> Decimal:
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        value = Decimal(raw)
    else:
        mixed = re.fullmatch(r"(?:(\d+)-)?(\d+)/(\d+)", raw)
        if mixed is None:
            raise ValueError(f"malformed FOMC numeric token: {raw!r}")
        denominator = Decimal(mixed.group(3))
        if denominator == 0:
            raise ValueError("FOMC numeric token has zero denominator")
        value = Decimal(mixed.group(2)) / denominator
        if mixed.group(1) is not None:
            value += Decimal(mixed.group(1))
    if not value.is_finite():
        raise ValueError("FOMC numeric token must be finite")
    return value


def _infer_published_at(html: str, meeting_date: date) -> datetime | None:
    compact = _normalized_html_text(html)
    match = re.search(
        r"For release at (\d{1,2}):(\d{2})\s+([ap])\.m\.,?\s+(E[DS]T)",
        compact,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    hour = int(match.group(1)) % 12
    if match.group(3).lower() == "p":
        hour += 12
    published = datetime.combine(
        meeting_date,
        time(hour=hour, minute=int(match.group(2))),
        tzinfo=ZoneInfo("America/New_York"),
    )
    if published.tzname() != match.group(4).upper():
        logger.debug(
            "FOMC release timezone mismatch: parsed=%s declared=%s",
            published.tzname(),
            match.group(4).upper(),
        )
        return None
    return published


def _infer_vote_split(html: str) -> str | None:
    vote = _infer_vote(html)
    return vote[1] if vote is not None else None


def _infer_vote(html: str) -> tuple[str, str] | None:
    paragraphs = _normalized_paragraphs(html)
    candidates: list[tuple[str, int]] = []
    for index, paragraph in enumerate(paragraphs):
        lowered = paragraph.lower()
        candidates.extend(
            ("notation", index)
            for _match in re.finditer(
                r"voting \(by notation\) for the monetary policy action",
                lowered,
            )
        )
        candidates.extend(
            ("regular", index)
            for _match in re.finditer(
                r"voting for the monetary policy action",
                lowered,
            )
        )
        candidates.extend(
            ("explicit", index)
            for _match in re.finditer(
                r"approved the following statement for release by",
                lowered,
            )
        )

    if len(candidates) > 1:
        raise NormalizationError(
            "FOMC statement contains multiple monetary-policy votes"
        )
    if candidates:
        family, index = candidates[0]
        paragraph = paragraphs[index]
        if family == "notation":
            if not paragraph.startswith(_NOTATION_PREFIX) or not paragraph.endswith(
                "."
            ):
                raise NormalizationError("FOMC malformed notation-vote paragraph")
            voters = _parse_named_voters(paragraph[len(_NOTATION_PREFIX) : -1])
            return "stated", f"{len(voters)}-0"
        if family == "regular":
            return "stated", _parse_regular_vote_block(paragraphs, index)
        return "stated", _parse_explicit_vote(paragraph)

    if any(_AGAINST_PREFIX.match(paragraph) for paragraph in paragraphs):
        raise NormalizationError(
            "FOMC voting-against paragraph has no voting-for block"
        )
    return None


def _parse_explicit_vote(paragraph: str) -> str:
    match = re.search(
        r"the federal open market committee approved the following statement "
        r"for release by (?:a )?(\d+)\s*-\s*(\d+)\s+vote\b",
        paragraph,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise NormalizationError("FOMC malformed published vote split")
    return f"{match.group(1)}-{match.group(2)}"


def _parse_regular_vote_block(paragraphs: list[str], index: int) -> str:
    paragraph, alternate_removed = _remove_alternate_suffix(paragraphs[index])
    if not paragraph.startswith(_FOR_PREFIX):
        raise NormalizationError("FOMC malformed monetary-policy voting paragraph")
    body = paragraph[len(_FOR_PREFIX) :]
    inline_against = re.search(
        r"\.\s+Voting against (?:this action|the action) (?:was|were) ", body
    )
    if inline_against is not None:
        for_raw = body[: inline_against.start()]
        against_raw = body[inline_against.end() :]
        _reject_later_against_paragraph(paragraphs, index + 1)
    else:
        if body.endswith("."):
            for_raw = body[:-1]
        elif alternate_removed:
            for_raw = body
        else:
            raise NormalizationError("FOMC monetary-policy voter list has no boundary")
        against_raw = _next_against_paragraph(paragraphs, index)
        _reject_later_against_paragraph(
            paragraphs,
            index + (2 if against_raw is not None else 1),
        )
    for_voters = _parse_named_voters(for_raw)
    against_voters = _parse_against_voters(against_raw) if against_raw else []
    overlap = {_voter_identity(name) for name in for_voters} & {
        _voter_identity(name) for name in against_voters
    }
    if overlap:
        raise NormalizationError("FOMC voter appears on both sides of the vote")
    return f"{len(for_voters)}-{len(against_voters)}"


def _next_against_paragraph(paragraphs: list[str], index: int) -> str | None:
    if index + 1 >= len(paragraphs):
        return None
    paragraph, _alternate_removed = _remove_alternate_suffix(paragraphs[index + 1])
    match = _AGAINST_PREFIX.match(paragraph)
    return paragraph[match.end() :] if match is not None else None


def _reject_later_against_paragraph(paragraphs: list[str], start: int) -> None:
    if any(_AGAINST_PREFIX.match(paragraph) for paragraph in paragraphs[start:]):
        raise NormalizationError("FOMC noncontiguous voting-against paragraph")


def _remove_alternate_suffix(paragraph: str) -> tuple[str, bool]:
    match = _ALTERNATE_SUFFIX.search(paragraph)
    if match is not None:
        return paragraph[: match.start()], True
    if "voted as an alternate member at this meeting" in paragraph:
        raise NormalizationError("FOMC malformed alternate-member note")
    return paragraph, False


def _parse_against_voters(raw: str) -> list[str]:
    voters: list[str] = []
    for clause in raw.removesuffix(".").split(";"):
        bounded = clause.strip().removeprefix("and ")
        rationale = re.search(r",\s+(?:who|each of whom)\b", bounded)
        names_only = bounded[: rationale.start()] if rationale is not None else bounded
        normalized_names = re.sub(r",?\s+and\s+", ",", names_only)
        for name in normalized_names.split(","):
            candidate = name.strip()
            if _VOTER_NAME.fullmatch(candidate) is None:
                raise NormalizationError(f"FOMC malformed named voter: {candidate!r}")
            voters.append(candidate)
    if not voters or len(set(voters)) != len(voters):
        raise NormalizationError("FOMC empty or duplicate named voter")
    return voters


def _parse_named_voters(raw: str) -> list[str]:
    parts = [part.strip() for part in raw.split(";")]
    if not parts or any(not part for part in parts):
        raise NormalizationError("FOMC empty named voter")
    voters: list[str] = []
    for index, part in enumerate(parts):
        if part.startswith("and "):
            if index != len(parts) - 1:
                raise NormalizationError(
                    "FOMC misplaced conjunction in named voter list"
                )
            part = part[4:].strip()
        if _VOTER_NAME.fullmatch(part) is None:
            raise NormalizationError(f"FOMC malformed named voter: {part!r}")
        voters.append(part)
    if len(set(voters)) != len(voters):
        raise NormalizationError("FOMC duplicate named voter")
    return voters


def _voter_identity(name: str) -> str:
    return re.sub(
        r",\s*(?:chair|vice chair)$", "", name, flags=re.IGNORECASE
    ).casefold()
