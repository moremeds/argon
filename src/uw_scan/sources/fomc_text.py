"""Strict extraction helpers for official FOMC statement text."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _ParsedVoters:
    names: tuple[str, ...]
    identities: frozenset[str]


@dataclass(frozen=True)
class ParsedVote:
    """A committee vote, with the voters the publisher actually named.

    ``voted_for``/``voted_against`` are empty when the statement publishes only
    a tally ("approved ... by a 9-1 vote"), which is a different fact from a
    unanimous vote.  ``names_stated`` separates the two so a consumer can never
    read "no dissenters named" as "no dissenters".
    """

    status: str
    split: str
    voted_for: tuple[str, ...] = ()
    voted_against: tuple[str, ...] = ()
    names_stated: bool = True


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
    return vote.split if vote is not None else None


def _infer_vote(html: str) -> ParsedVote | None:
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
            return ParsedVote(
                status="stated",
                split=f"{len(voters.names)}-0",
                voted_for=voters.names,
            )
        if family == "regular":
            return _parse_regular_vote_block(paragraphs, index)
        return ParsedVote(
            status="stated",
            split=_parse_explicit_vote(paragraph),
            names_stated=False,
        )

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


def _parse_regular_vote_block(paragraphs: list[str], index: int) -> ParsedVote:
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
    against_voters = (
        _parse_against_voters(against_raw)
        if against_raw
        else _ParsedVoters((), frozenset())
    )
    if for_voters.identities & against_voters.identities:
        raise NormalizationError("FOMC voter appears on both sides of the vote")
    return ParsedVote(
        status="stated",
        split=f"{len(for_voters.names)}-{len(against_voters.names)}",
        voted_for=for_voters.names,
        voted_against=against_voters.names,
    )


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


#: Where a dissenter's names end and their reason begins.
_RATIONALE_PREFIX = re.compile(r",\s+(?:who|each of whom)\b")
#: The Fed separates dissent clauses with ``;``/``; and``, and — when the
#: dissenters want opposite things — with a bare ``, and``.  Semicolon first:
#: it never occurs inside one of these rationales, while ``, and`` can.
_CLAUSE_SEMICOLON = re.compile(r";\s*(?:and\s+)?")
_CLAUSE_COMMA = re.compile(r",\s+and\s+")


def _parse_against_voters(raw: str) -> _ParsedVoters:
    """Read every dissenter, not only the first.

    Splitting on ``;`` alone read the October 2025 two-sided dissent as a single
    clause.  That statement separated its dissenters with ``, and`` rather than
    ``;`` because they wanted opposite things (Miran a deeper cut, Schmid no
    cut), so everything after the first ``, who`` was discarded as rationale --
    taking Schmid with it.  ``split`` is derived from the surviving names, so the
    release came out self-consistently wrong at 10-1 and still reported ``ok``:
    a dropped dissenter is invisible to a count that the drop also decremented.

    Each rationale must be claimed by a non-empty group of names, or the release
    fails closed.  Losing a dissenter quietly is the one error this parser must
    never make -- the composition carries the signal a tally cannot recover.
    """
    body = raw.strip().removesuffix(".")
    rationales = list(_RATIONALE_PREFIX.finditer(body))
    if not rationales:
        # No reasons given: the whole block is names.
        return _validated_voters(_tokenize_voter_names(body.removeprefix("and ")))

    voters: list[str] = []
    span_start = 0
    for position, rationale in enumerate(rationales):
        span = body[span_start : rationale.start()]
        # After the first clause the span still carries the PREVIOUS dissenter's
        # reason, which runs up to the separator that opens this one.
        names = span if position == 0 else _names_after_separator(span)
        parsed = _tokenize_voter_names(names.strip().removeprefix("and "))
        if not parsed:
            raise NormalizationError("FOMC voting-against clause names no dissenter")
        voters.extend(parsed)
        span_start = rationale.end()
    return _validated_voters(voters)


def _names_after_separator(span: str) -> str:
    """The tail of ``span`` that belongs to the next dissenter, not the last one.

    Takes the FIRST separator rather than the last: a name list is itself comma
    separated ("Hammack, Kashkari, and Logan"), so the last ``, and`` sits
    *inside* the names and would keep only the final one.
    """
    for separator in (_CLAUSE_SEMICOLON, _CLAUSE_COMMA):
        match = separator.search(span)
        if match is not None:
            return span[match.end() :]
    raise NormalizationError("FOMC voting-against clauses have no separator")


def _tokenize_voter_names(raw: str) -> list[str]:
    voters: list[str] = []
    position = 0
    terminal_conjunction = False
    while position < len(raw):
        match = _VOTER_NAME.match(raw, position)
        if match is None:
            raise NormalizationError(f"FOMC malformed named voter: {raw[position:]!r}")
        voters.append(match.group())
        position = match.end()
        if position == len(raw):
            return voters
        if terminal_conjunction:
            raise NormalizationError(f"FOMC malformed named voter list: {raw!r}")
        separator = re.match(r"(?:,\s+and\s+|\s+and\s+|,\s+)", raw[position:])
        if separator is None:
            raise NormalizationError(f"FOMC malformed named voter list: {raw!r}")
        terminal_conjunction = "and" in separator.group()
        position += separator.end()
    raise NormalizationError(f"FOMC malformed named voter list: {raw!r}")


def _parse_named_voters(raw: str) -> _ParsedVoters:
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
    return _validated_voters(voters)


def _validated_voters(voters: list[str]) -> _ParsedVoters:
    identities = frozenset(_voter_identity(name) for name in voters)
    if not voters or len(identities) != len(voters):
        raise NormalizationError("FOMC empty or duplicate named voter")
    return _ParsedVoters(tuple(voters), identities)


def _voter_identity(name: str) -> str:
    return re.sub(
        r",\s*(?:chair|vice chair)$", "", name, flags=re.IGNORECASE
    ).casefold()
