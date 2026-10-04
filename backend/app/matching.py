"""Resolving a spoken name to patient records.

This module decides who is a *candidate*, never who the caller is. Picking one
of several candidates is the tool layer's job to refuse and the policy engine's
job to escalate — cv_0007 is explicit that guessing is a wrong answer, not an
unlucky one.

Deliberately generous: it is safe to return too many candidates, because that
escalates. It is not safe to return too few, because that books the wrong
person. "Imran Qureshi" and "Imraan Quraishi" are two different people in
clinic.json whose names sound identical, and both must come back.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Set

HONORIFICS = {
    "ji", "sahab", "saheb", "sahib", "shri", "shrimati", "smt",
    "mr", "mrs", "ms", "miss", "sir", "madam", "maam",
    "dr", "doctor",
}

# Applied in order. Collapses the spelling variation that romanised Hindi names
# carry: Imraan/Imran, Quraishi/Qureshi, Vikas/Wikas.
_PHONETIC_RULES = (
    ("aa", "a"), ("ee", "i"), ("oo", "u"),
    ("ai", "e"), ("ei", "e"),
    ("q", "k"), ("sh", "s"), ("w", "v"), ("y", "i"),
)

_NON_NAME = re.compile(r"[^a-z\s]")
_SPACES = re.compile(r"\s+")


def normalise(name: str) -> str:
    lowered = (name or "").lower().replace(".", " ").replace("-", " ")
    return _SPACES.sub(" ", _NON_NAME.sub(" ", lowered)).strip()


def tokens(name: str) -> List[str]:
    """Name parts, honorifics dropped. 'Sharma ji' -> ['sharma']."""
    return [t for t in normalise(name).split() if t and t not in HONORIFICS]


def phonetic(token: str) -> str:
    out = token
    for source, target in _PHONETIC_RULES:
        out = out.replace(source, target)
    return re.sub(r"(.)\1+", r"\1", out)


def strongly_align(query_token: str, record_token: str) -> bool:
    """Two real name parts that agree, exactly or by sound."""
    return query_token == record_token or phonetic(query_token) == phonetic(record_token)


def initial_aligns(query_token: str, record_token: str) -> bool:
    """'R.' standing in for 'Rajesh', in either direction."""
    if len(query_token) == 1 and record_token.startswith(query_token):
        return True
    return len(record_token) == 1 and query_token.startswith(record_token)


def tokens_align(query_token: str, record_token: str) -> bool:
    return strongly_align(query_token, record_token) or initial_aligns(
        query_token, record_token
    )


def name_matches(query: str, record_name: str) -> bool:
    """True when the shorter name aligns into the longer one, token by token.

    Symmetric on purpose. Callers give both more and less than the record holds
    — "Rajesh Kumar Sharma" has to reach the record written "Rajesh Sharma",
    and "Sharma" has to reach all three. Each token is consumed once, via a
    bipartite matching rather than a greedy pass, so one record token cannot
    satisfy two query tokens.

    At least one pair must agree on a real name part of two or more characters.
    Without that, a caller saying "K" resolves to "R. K. Sharma" and the agent
    books a confidently wrong patient — initials corroborate an identity, they
    never establish one.
    """
    query_tokens = tokens(query)
    record_tokens = tokens(record_name)
    if not query_tokens or not record_tokens:
        return False

    needles, haystack = (
        (query_tokens, record_tokens)
        if len(query_tokens) <= len(record_tokens)
        else (record_tokens, query_tokens)
    )

    if not any(
        len(needle) > 1 and len(straw) > 1 and strongly_align(needle, straw)
        for needle in needles
        for straw in haystack
    ):
        return False

    # Kuhn's algorithm. Token counts are tiny, so the cost is irrelevant.
    assigned: Dict[int, int] = {}

    def try_assign(needle_index: int, seen: Set[int]) -> bool:
        for straw_index, straw in enumerate(haystack):
            if straw_index in seen or not tokens_align(needles[needle_index], straw):
                continue
            seen.add(straw_index)
            if straw_index not in assigned or try_assign(assigned[straw_index], seen):
                assigned[straw_index] = needle_index
                return True
        return False

    return all(try_assign(index, set()) for index in range(len(needles)))


def find_by_name(query: str, patients: Sequence[Dict]) -> List[Dict]:
    """Every patient whose name the query could plausibly refer to."""
    return [p for p in patients if name_matches(query, p["name"])]


def normalise_phone(phone: str) -> str:
    """Digits only, last 10 kept. Handles '+91 98122 00011' and '09812200011'."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits