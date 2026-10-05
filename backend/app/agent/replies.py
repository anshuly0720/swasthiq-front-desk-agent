"""Replies, assembled only from values a tool returned.

schema.md scores `reply` for not containing invented facts, not for wording.
So every template takes its nouns -- doctor, date, time, appointment id -- from
a tool result, and no template has a slot for anything the model wrote.
"""

from __future__ import annotations

from typing import Optional

EMERGENCY = ("Main abhi aapko clinic se connect kar rahi hoon. Agar takleef badh rahi hai, "
             "turant nazdeeki emergency par jaiye.")
ADVICE = ("Ye sawaal main nahi bata sakti. Main aapko clinic staff se connect kar rahi hoon, "
          "wo aapko sahi salah denge.")
NOT_AUTHORISED = ("Kisi aur ke appointment mein badlav main nahi kar sakti. Main aapko clinic "
                  "staff se connect kar rahi hoon.")
AMBIGUOUS = ("Is naam se ek se zyada record hain, isliye main khud se chun nahi sakti. "
             "Main aapko clinic staff se connect kar rahi hoon.")
OUT_OF_SCOPE = "Ye front desk se nahi ho payega. Main aapko clinic staff se connect kar rahi hoon."
REFUSED = ("Maaf kijiye, ye main nahi kar sakti. Appointment book, reschedule ya cancel karne "
           "mein zaroor madad kar sakti hoon.")
NOTHING_HEARD = "Maaf kijiye, aapki baat saaf nahi aayi. Aap dobara call kar sakte hain."


def booked(doctor_name: str, date: str, start: str) -> str:
    return "Ji, {} ko {} baje {} ke saath appointment book ho gaya hai.".format(
        date, start, doctor_name)


def rescheduled(doctor_name: str, date: str, start: str) -> str:
    return "Ji, appointment {} ko {} baje {} ke saath shift kar diya hai.".format(
        date, start, doctor_name)


def cancelled(doctor_name: str, date: str, start: str) -> str:
    return "Ji, {} ka {} baje wala appointment {} ke saath cancel kar diya hai.".format(
        date, start, doctor_name)


def no_slots(doctor_name: str, date: str, reason: Optional[str]) -> str:
    if reason == "CLINIC_HOLIDAY":
        return "Us din {} clinic band hai, isliye koi slot nahi hai.".format(date)
    if reason == "DOCTOR_ON_LEAVE":
        return "{} us din {} ko chhutti par hain.".format(doctor_name, date)
    if reason == "NO_WINDOW":
        return "{} us din {} ko baithte nahi hain.".format(doctor_name, date)
    return "{} ke saath {} ko koi slot khali nahi hai.".format(doctor_name, date)


def slot_not_free(doctor_name: str, date: str, start: str) -> str:
    return "{} ko {} baje {} ke saath slot khali nahi hai.".format(date, start, doctor_name)