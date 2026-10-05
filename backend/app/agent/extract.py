"""Turning a conversation into a structured intent.

The model fills this in when a key is configured; these rules fill it in when
one is not, and are the fallback whenever the model's answer fails validation.
Either way the *resolution* happens here in Python: a name becomes a patient id
only via lookup_patient, and a phrase becomes a date only via dates.py. Nothing
downstream ever sees text the model wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..matching import find_by_name, strongly_align, tokens as name_tokens
from .dates import detect_part_of_day, resolve_date, resolve_time

INTENTS = ("book", "reschedule", "cancel", "ask_availability", "none")

_PHONE = re.compile(r"\b(\d{10})\b")
_CHUNK = re.compile(r"[,.!?;\u2026]|\.\.\.|\bnahi nahi\b|\bbalki\b")
# A name window may not cross punctuation or a run of digits.
_NAME_SEGMENT = re.compile(r"[,.;!?\u2026\u0964]|\d+")

_CANCEL = re.compile(r"\b(cancel|radd|rad kar)\b")
_RESCHEDULE = re.compile(r"\b(reschedule|postpone|prepone|shift|badal|badlna|aage badha|"
                         r"karwana hai|kara dijiye|kar dijiye)\b")
_EXISTING = re.compile(r"\b(mera|meri|mere|unka|unki)\s+[\w\s]{0,20}?appointment\b|"
                       r"\bappointment hai\b")
_BOOK = re.compile(r"\b(appointment|milna|milne|dikhana|dikhane|aa sakta|aa sakti|slot|"
                   r"time mil|book)\b")

_GAVE_UP = re.compile(r"\b(baad mein|baad me|phir call|rehne d|koi baat nahi|later|"
                      r"call back|main baad)\b")
_INJECTION = re.compile(r"(ignore (your |all )?previous instructions|administrator mode|"
                        r"admin mode|system prompt|you are now|developer mode|"
                        r"authorised internal test|authorized internal test|"
                        r"override|jailbreak|disregard (your|the) (above|previous))")
_BULK = re.compile(r"\b(every appointment|all appointments|all the appointments|"
                   r"sabhi appointment|saare appointment|sab appointment|"
                   r"cancel every|cancel all)\b")

# "<name> ke liye", "<name> ko dikhana", "<name> ka appointment" -> the booking
# is for that person, who may not be the caller.
_SUBJECT_MARKERS = (
    r"ke liye", r"ko dikhana", r"ko dikhane", r"ka appointment", r"ki appointment",
    r"mere bete", r"meri beti", r"mera beta", r"meri bachchi", r"ke naam",
    r"for my", r"for ",
)
# "mere bete ke liye" names a relationship but no person. With two children on
# one record, that is not enough to book.
_UNNAMED_RELATIVE = re.compile(r"\b(mere bete|mera beta|meri beti|meri bachchi|mere bachche|"
                               r"my son|my daughter|my child|mere ladke)\b")
# A phone number counts as a caller marker: people recite their own number.
# It is proximity evidence only -- authorisation still requires a guardianship.
_CALLER_MARKERS = (r"\bmain\b", r"\bmai\b", r"bol rahi", r"bol raha", r"\bmera naam\b",
                   r"\bmy name\b", r"\bthis is\b", r"\bi am\b", r"\b\d{10}\b")


def _marker_distance(text: str, start: int, length: int, markers) -> Optional[int]:
    """Characters from this name to the nearest marker of a kind, or None.

    Distance rather than a yes/no window: when a turn carries both kinds, the
    closer marker is the one that describes this name.
    """
    best = None
    for marker in markers:
        for found in re.finditer(marker, text):
            if found.start() >= start + length:
                gap = found.start() - (start + length)
            elif found.end() <= start:
                gap = start - found.end()
            else:
                gap = 0
            if gap <= 45 and (best is None or gap < best):
                best = gap
    return best


def _trim_to_name(window: str, patients) -> str:
    """"Main Harpreet Singh number" -> "Harpreet Singh".

    Keeps only the words that agree with a candidate's recorded name, so the
    trace shows what the caller was identified by rather than the sentence it
    sat in. Initial-style agreement is deliberately excluded here: it would
    keep "ke" because "K." is an initial.
    """
    candidates = find_by_name(window, patients)
    if not candidates:
        return window
    recorded = set()
    for candidate in candidates:
        recorded |= set(name_tokens(candidate["name"]))
    kept = [word for word in window.split()
            if any(strongly_align(t, r) for t in name_tokens(word) for r in recorded)]
    return " ".join(kept) or window


@dataclass
class Extraction:
    intent: str = "none"
    doctor_id: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    part_of_day: Optional[str] = None
    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None
    subject_name: Optional[str] = None
    subject_unnamed_relative: bool = False
    model_clinical_urgent: bool = False
    model_clinical_evidence: str = ""
    model_medical_advice: bool = False
    date_conflict: Optional[str] = None
    gave_up: bool = False
    injection: bool = False
    bulk: bool = False
    source: str = "rules"
    notes: List[str] = field(default_factory=list)


def _chunks(turn: str) -> List[str]:
    return [c for c in _CHUNK.split(turn) if c and c.strip()]


def extract(turns: List[str], today: str, store) -> Extraction:
    out = Extraction()
    joined = " ".join(turns).lower()

    out.injection = bool(_INJECTION.search(joined))
    out.bulk = bool(_BULK.search(joined))
    out.gave_up = bool(_GAVE_UP.search(joined))
    out.subject_unnamed_relative = bool(_UNNAMED_RELATIVE.search(joined))    

    # --- doctor: surname of a doctor in clinic.json -----------------------
    # Devanagari spellings of the same surnames, so a caller writing in Hindi
    # script reaches the same doctor. Mapped to the romanised surname rather
    # than to an id, so this keeps working if clinic.json changes.
    devanagari_surnames = {"राव": "rao", "सेठी": "sethi", "सेठि": "sethi"}
    for script_form, surname in devanagari_surnames.items():
        if script_form in joined:
            joined += " " + surname

    for doctor in store.all_doctors():
        surname = doctor["name"].split()[-1].lower()
        if re.search(r"\b" + re.escape(surname) + r"\b", joined):
            out.doctor_id = doctor["id"]

    # --- date and time: the last thing said wins --------------------------
    # A caller correcting themselves mid-sentence ("mangalwar 6 tareekh... nahi
    # nahi, budhwar, 7 tareekh") means the later phrase, not the earlier one.
    for turn in turns:
        for chunk in _chunks(turn):
            resolved = resolve_date(chunk, today)
            if resolved:
                out.date = resolved["date"]
                out.date_conflict = resolved["conflict"] or out.date_conflict
            lowered = chunk.lower()
            if re.search(r"(baje|:|\bam\b|\bpm\b|saadhe|sawa|paune)", lowered):
                clock = resolve_time(chunk)
                if clock:
                    out.time = clock
            part = detect_part_of_day(chunk)
            if part:
                out.part_of_day = part

    # --- phone ------------------------------------------------------------
    phones = _PHONE.findall(joined)
    if phones:
        out.caller_phone = phones[-1]

    # --- names: every window of 1-3 words that matches a patient ----------
    patients = store.all_patients()
    hits = []
    for turn in turns:
        lowered = turn.lower()
        # Segment on punctuation and digits before building name windows.
        # "Sunita Gupta, 9812200166, Aarav ke liye" strips to the word list
        # [sunita, gupta, aarav], which makes "Sunita Gupta Aarav" look like one
        # name spanning two different patients. A phone number between two names
        # separates them; it does not join them.
        for segment in _NAME_SEGMENT.split(turn):
            if not segment.strip():
                continue
            offset = lowered.find(segment.lower())
            words = re.findall(r"[A-Za-z\u0900-\u097F.]+", segment)
            for size in (3, 2, 1):
                for index in range(len(words) - size + 1):
                    window = " ".join(words[index:index + size])
                    if window.lower() in ("main", "dr", "dr.", "ji", "hai", "ke", "ka", "ki"):
                        continue
                    if not find_by_name(window, patients):
                        continue
                    trimmed = _trim_to_name(window, patients)
                    position = lowered.find(trimmed.lower(), max(offset, 0))
                    if position < 0:
                        position = lowered.find(trimmed.lower())
                    if position < 0:
                        position = max(offset, 0)
                    hits.append((trimmed,
                                 _marker_distance(lowered, position, len(trimmed),
                                                  _SUBJECT_MARKERS),
                                 _marker_distance(lowered, position, len(trimmed),
                                                  _CALLER_MARKERS)))
    # longest window first, so "Harpreet Singh" beats "Harpreet"
    hits.sort(key=lambda hit: -len(hit[0]))

    subject = caller = None
    # Nearest marker wins. "Sunita Gupta, 9812200166. Aarav ke liye." puts both
    # a caller marker and a subject marker within reach of both names; whichever
    # marker sits closer to a name is the one that describes it. A boolean
    # in-range test cannot separate those and books the guardian for the child.
    for window, to_subject, to_caller in hits:
        if to_subject is None and to_caller is None:
            continue
        prefers_subject = to_caller is None or (
            to_subject is not None and to_subject < to_caller)
        if prefers_subject and subject is None and window != caller:
            subject = window
        elif not prefers_subject and caller is None and window != subject:
            caller = window
    # Only then fall back to an unmarked name, and only for a role still empty.
    # Assigning on no evidence first is what let the subject take the caller
    # slot and hide an authorisation failure.
    if caller is None:
        for window, _s, _c in hits:
            if window != subject:
                caller = window
                break
    if subject is None and caller is None and hits:
        caller = hits[0][0]

    out.caller_name, out.subject_name = caller, subject

    # --- intent -----------------------------------------------------------
    if _CANCEL.search(joined):
        out.intent = "cancel"
    elif _EXISTING.search(joined) and _RESCHEDULE.search(joined) and out.date:
        out.intent = "reschedule"
    elif _BOOK.search(joined):
        out.intent = "book"
    elif out.doctor_id and out.date:
        # cv_0015 never says "appointment": naming a doctor and a day at a front
        # desk is a booking request.
        out.intent = "book"
    return out