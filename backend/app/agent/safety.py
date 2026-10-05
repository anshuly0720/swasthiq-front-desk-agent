"""The clinical screen.

Two jobs, both narrow on purpose:

  clinical_urgent - something that needs a clinician now. The brief's one hard
                    rule: the booking flow stops the moment this appears, and a
                    submission that books through it is rejected outright.
  medical_advice  - a clinical judgement the front desk cannot give.

Narrow matters in both directions. Miss an emergency and the submission fails;
fire on every mention of fever and the restraint score goes to zero. Fever,
cough and stomach ache are ordinary reasons to see a doctor, so they are not
here. Chest pain and breathlessness are, in Hinglish, English and Devanagari.

This runs before and independently of the model. Either the lexicon or the
model is enough to escalate, because the cost of a miss is not symmetric with
the cost of a false alarm.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

RED_FLAGS: List[Tuple[str, str]] = [
    (r"seene?\s*(mein|me)?\b.{0,20}?\bdard", "chest pain"),
    (r"ch(aa)?ti\s*(mein|me)?\b.{0,20}?\bdard", "chest pain"),
    (r"chest\s*(pain|tightness|pressure)", "chest pain"),
    (r"सीने\s*में\s*दर्द", "chest pain"),
    (r"छाती\s*में\s*दर्द", "chest pain"),
    (r"saans?\b.{0,24}?\b(nahi|nhi)\s*(aa|a)\b", "cannot breathe"),
    (r"saans?\b.{0,24}?\b(phool|fool|ukhad)", "breathlessness"),
    (r"saans?\b.{0,24}?\b(takleef|dikkat|problem)", "breathlessness"),
    (r"(breathless|short(ness)? of breath|can.?t breathe|difficulty breathing)", "breathlessness"),
    (r"(सांस|साँस).{0,20}?(तकलीफ|दिक्कत)", "breathlessness"),
    (r"(सांस|साँस).{0,20}?(नहीं|नही)\s*आ", "cannot breathe"),
    (r"\bbehosh\b", "unconscious"),
    (r"(unconscious|passed out|fainted|not responding|unresponsive)", "unconscious"),
    (r"\b(daura|dauraa|mirgi)\b", "seizure"),
    (r"(seizure|convulsion|fitting)", "seizure"),
    (r"\b(lakwa|lakva)\b", "stroke signs"),
    (r"(stroke|slurred speech|face droop)", "stroke signs"),
    (r"बेहोश", "unconscious"),
    (r"(bahut|zyada|bohot)\s*kh(oo|u)n", "heavy bleeding"),
    (r"kh(oo|u)n\s*(beh|bah|nikal)", "heavy bleeding"),
    (r"(bleeding heavily|heavy bleeding|haemorrhag|hemorrhag)", "heavy bleeding"),
    (r"\b(zeher|zahar)\b", "poisoning"),
    (r"(poison(ing|ed)?|overdose)\b", "poisoning or overdose"),
    (r"खून\s*(बह|निकल)", "heavy bleeding"),
    (r"(suicid|self.?harm|khud.?kushi|aatmahatya)", "self-harm"),
    (r"(heart attack|cardiac arrest|dil ka daura)", "cardiac event"),
    (r"(anaphyla|throat clos|lips? (turning )?blue|neel pad)", "airway or allergic"),
]

ADVICE_PATTERNS: List[Tuple[str, str]] = [
    (r"(goli|tablet|dawai|dawa|medicine|dose|khurak)\b.{0,12}?\b(le|lu|lun|loon|leni|lena|take)\b",
     "asked whether to take medication"),
    (r"(le lun|le loon|lu ya nahi|lun ya nahi|loon ya nahi|leni chahiye)",
     "asked whether to take medication"),
    (r"(should i take|can i take|how much should i|how many should i)", "asked for a dose"),
    (r"(kitni der|kitne din|kab tak).{0,30}?(utar|theek|thik|band|better)",
     "asked how long symptoms should last"),
    (r"(serious hai|serious h|khatarnak|is it serious|should i worry)",
     "asked whether symptoms are serious"),
    (r"(side ?effect|safe hai|safe h|interaction)", "asked about a drug's effects"),
    (r"(kya karu|kya karoon|what should i do about).{0,30}?(dard|bukhar|fever|pain)",
     "asked what to do about symptoms"),
]

_NEGATORS = (r"\bnahi\b", r"\bnahin\b", r"\bnhi\b", r"\bna\b", r"\bno\b", r"\bnot\b",
             r"\bnever\b", r"नहीं", r"नही")
_NEGATOR_RE = re.compile("|".join(_NEGATORS))

# "le lun ya nahi" is an either/or question, not a denial. Without this the
# negation check swallows every request for advice -- and worse, an emergency
# followed by a question in the same breath.
_QUESTION_MARKERS = re.compile(r"\bya\s+(nahi|nahin|nhi)\b|\bor\s+not\b")
_CLAUSE_SPLIT = re.compile(r"[,.?!;\u0964]")


def _clauses(text: str):
    start = 0
    for match in _CLAUSE_SPLIT.finditer(text):
        yield start, text[start:match.start()]
        start = match.end()
    yield start, text[start:]


def _negated_around(clause: str, start: int, end: int) -> bool:
    """A denial sits beside the phrase, not inside it.

    Only text outside the match counts, because some red flags carry a negator
    as part of the finding: "saans nahi aa rahi" IS the emergency. Checking the
    whole clause would read its own wording as a denial and let it through.
    """
    outside = clause[:start] + " " + clause[end:]
    return bool(_NEGATOR_RE.search(_QUESTION_MARKERS.sub(" ", outside)))


def _scan(text: str, patterns, kind: str) -> Optional[dict]:
    for _offset, clause in _clauses(text):
        if not clause.strip():
            continue
        for pattern, label in patterns:
            match = re.search(pattern, clause)
            # Negation is scoped to the clause carrying the match, so
            # "seene mein dard hai, goli le lun ya nahi?" stays an emergency.
            if match and not _negated_around(clause, match.start(), match.end()):
                return {"kind": kind, "finding": label, "evidence": match.group(0).strip()}
    return None


def screen_turn(turn: str) -> Optional[dict]:
    text = (turn or "").lower()
    if not text.strip():
        return None
    return _scan(text, RED_FLAGS, "clinical_urgent") or _scan(text, ADVICE_PATTERNS, "medical_advice")


def screen(turns: List[str]) -> Optional[dict]:
    """First concerning turn, with its index. Order matters: the booking stops here."""
    for index, turn in enumerate(turns):
        hit = screen_turn(turn)
        if hit:
            return dict(hit, turn_index=index)
    return None