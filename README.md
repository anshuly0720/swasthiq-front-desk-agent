# Clinic Front Desk Agent

**Anshul Kumar Yadav** — SwasthiQ SDE Intern assignment, October 2026

- **Live app** — <https://swasthiq-front-desk-agent.vercel.app>
- **API** — <https://swasthiq-front-desk-agent.onrender.com> (`/health`, `POST /agent/run`)

The API is on Render's free tier, which sleeps after about 15 minutes idle: the
first request after a pause takes 30–60 seconds, then it is fast.

A conversational front desk for Sunrise Clinic, Dehradun. It books, reschedules
and cancels appointments, and it knows which calls it must not handle at all.

---

## Run it

One command, from the repository root:

```bash
./start.sh          # macOS / Linux
start.bat           ::  Windows
```

That creates the virtualenv if it is missing, installs dependencies, and serves
`POST /agent/run` on <http://127.0.0.1:8000>. Neither Docker nor Node is needed
for the graded endpoint.

The agent runs **without an API key**. Extraction falls back to the rule-based
path and every one of the 23 test conversations still reaches the correct
terminal state; the model raises the ceiling on phrasings the rules do not
cover. To use it, put a Gemini key in `backend/.env` (the script creates the
file from `.env.example` on first run).

### The two screens

```bash
cd frontend
cp .env.example .env
npm install && npm run dev        # http://localhost:5173
```

Or open the live link at the top of this file — the frontend is deployed and
points at the deployed API.

### Replaying the conversation scripts

```bash
python runner.py --repeat 3 --url http://127.0.0.1:8000/agent/run
python check.py                       # scores results/ against each script's `expected`
python runner.py --dir adversarial --out results_adv --repeat 3 --url http://127.0.0.1:8000/agent/run
python check.py --dir adversarial --results results_adv
```

`runner.py` is the file you shipped, unchanged. `check.py` is mine: the starter
README says comparing results against `expected` is the candidate's job.

---

## The design in one sentence

**The model interprets what the caller said; code decides what happens; every
fact in a reply came back from a tool.**

```
turns ─┬─► clinical screen (plain Python)   red-flag lexicon, Hinglish + Devanagari
       │
       └─► Gemini, one call, temperature 0  per conversation: intent, doctor,
                                            date phrase, time phrase, who is
                                            calling, who it is for, flags
                    │
                    ▼
       policy engine (pure Python state machine)
         • the model's date phrase is re-resolved in Python against `today`
         • the model's name is re-resolved through lookup_patient
         • mutations run only after every turn has been read
                    │
                    ▼
       reply assembled from templates filled with tool results only
```

Three properties follow from that split, and all three are graded:

**Determinism.** The set of tool names is a function of the extracted state, not
of a sample from a model. Three runs of the same conversation produce the same
fingerprint.

**Grounding.** The model never emits a patient id, an appointment id or an ISO
date. There is no path from caller text to an identifier in the response — a
confident wrong answer from the model becomes a failed lookup, not a wrong
booking.

**The hard rule.** The clinical screen runs before any tool call, so a red flag
in the final turn still arrives before a booking could commit. That is enforced
by control flow, not by instructing the model.

---

## API contract

### `POST /agent/run`

The only endpoint used for grading. Request:

```json
{ "conversation_id": "cv_0001", "today": "2026-10-01", "turns": ["...", "..."] }
```

Response — exactly the keys in `schema.md`, nothing more:

```json
{
  "conversation_id": "cv_0001",
  "tool_calls": [{"name": "search_slots", "arguments": {"doctor_id": "dr_rao", "date": "2026-10-03"}}],
  "terminal_state": "booked",
  "escalation_reason": null,
  "patient_id": "pt_0013",
  "appointment_id": "ap_0026",
  "reply": "Ji, 2026-10-03 ko 09:00 baje Dr. Anjali Rao ke saath appointment book ho gaya hai.",
  "metrics": {"turns": 3, "tokens": 1050, "latency_ms": 3304, "model": "gemini-2.5-flash", "source": "gemini"}
}
```

`tool_calls` includes failed calls. `terminal_state` is one of `booked`,
`rescheduled`, `cancelled`, `escalated`, `refused`, `abandoned`.
`escalation_reason` is one of `clinical_urgent`, `medical_advice`,
`not_authorised`, `ambiguous_patient`, `out_of_scope`, and is `null` unless the
state is `escalated`.

### The six tools

Implemented against `clinic.json`. **This layer never imports a model client** —
it is the ground truth the agent is checked against, so it cannot depend on the
thing being checked.

| Tool | Arguments | Notes |
|---|---|---|
| `search_slots` | `doctor_id`, `date`, `part_of_day?` | A holiday, a leave day or a day the doctor does not work returns `available: false` with a reason, not an error |
| `lookup_patient` | `name?`, `phone?`, `patient_id?` | Returns every candidate, never a guess. Each carries guardianships and active appointments |
| `book_appointment` | `patient_id`, `doctor_id`, `date`, `start`, `booked_by?` | |
| `reschedule_appointment` | `appointment_id`, `date`, `start`, `requested_by?` | Keeps the same id — the appointment moved, it was not replaced |
| `cancel_appointment` | `appointment_id`, `requested_by?` | Frees the slot |
| `escalate_to_human` | `reason`, `detail` | `reason` must be one of the five in `schema.md` |

Malformed arguments return a named code and the fix, never a generic 500:
`INVALID_ARGUMENTS`, `UNKNOWN_DOCTOR`, `UNKNOWN_PATIENT`, `UNKNOWN_APPOINTMENT`,
`INVALID_DATE`, `INVALID_TIME`, `DATE_IN_PAST`, `CLINIC_HOLIDAY`,
`DOCTOR_ON_LEAVE`, `NO_WINDOW`, `OFF_GRID_TIME`, `SLOT_TAKEN`, `NOT_AUTHORISED`,
`APPOINTMENT_NOT_ACTIVE`, `NOTHING_TO_CHANGE`, `INVALID_ESCALATION_REASON`,
`UNKNOWN_TOOL`.

**A slot cannot be double-booked.** That is a partial unique index on
`(doctor_id, date, start)` over active appointments plus `BEGIN IMMEDIATE`, not
an application-level check — a read-then-write check has a race window by
construction. `backend/tests/test_race.py` fires 20 threads at one slot and
asserts exactly one wins.

### UI endpoints

Not part of the graded contract: `GET /ui/stats`, `GET /ui/handoffs`,
`GET /ui/conversations/{id}`, `POST /ui/handoffs/{id}/resolve`.

---

## Model, tokens and latency

**Model: `gemini-2.5-flash`**, temperature 0, one call per conversation,
schema-constrained JSON output.

`gemini-2.0-flash` was retired during this assignment and `gemini-3.8-flash`
returns `RESOURCE_EXHAUSTED` on a free key, so the model was chosen by probing
what the key actually serves rather than by name.

<!-- Regenerate with: python metrics_table.py -->

Measured per conversation, first (uncached) call, from the `metrics` block of
real result files:

| Conversation | Where | Tokens | Latency | Source |
|---|---|---|---|---|
| `cv_0001` booked | local | 1,050 | 3,304 ms | gemini |
| `cv_0009` escalated / not_authorised | local | 1,547 | 4,019 ms | gemini |
| `cv_0011` escalated / clinical_urgent | **deployed** | 1,178 | 4,809 ms | gemini |
| repeat run, prompt cache hit | local | 0 | 20–60 ms | gemini (cached) |

So roughly **1,000–1,600 tokens** and **3–5 seconds** per conversation, one model
call each, with repeat runs served from the prompt cache in tens of milliseconds.

`python metrics_table.py` regenerates this from whatever is in `results/` and
`results_adv/`.

**Some rows in a fresh sweep will show `rules_fallback` with zero tokens.** That
is not an error path being hit by accident: the Gemini free tier has a daily
request cap, and a full sweep of 23 conversations run three times exhausts it.
When that happens the rule-based extractor completes the conversation and
`metrics.source` says so. Every one of the 23 cases reaches its correct terminal
state on that path, which is why the fallback is a design decision rather than a
safety net.

Latency is measured **server-side**, from the `metrics` block. The runner's
client-side wall clock reported ~2,040 ms against a stub whose own measurement
was 1 ms: Windows resolves `localhost` to IPv6 first while uvicorn listens on
IPv4. Calling `127.0.0.1` directly gives 70 ms. The client figure measured a
resolver, not the agent.

### When the model is unavailable

Free-tier quota is finite and the hidden set is ~25 conversations run three
times. Three mitigations, all disclosed:

- **Pacing** — `LLM_MIN_INTERVAL` (default 4s) keeps a sweep under the
  per-minute cap.
- **Caching** — identical prompts are cached on disk. `LLM_CACHE=0` disables it,
  and determinism was verified with it off.
- **Fallback** — a 429, a timeout or an off-schema response falls through to the
  rule-based extractor. The conversation completes; `metrics.source` reports
  `rules_fallback` so the degradation is visible rather than silent.

---

## Determinism

`runner.py --repeat 3` reports **deterministic across 3 runs** for all 15 starter
scripts and all 8 adversarial cases. Same terminal state, same escalation
reason, same set of tool names, every time.

---

## Tests

```bash
cd backend && pytest -q
```

138 tests. Beyond the happy paths: every error code, the Monday window overlap
collapsing to 24 slots, Sunday and holiday and leave days, the three Sharmas and
the two Qureshis, the 20-thread race, malformed and extra tool arguments, denied
symptoms, Devanagari input, hostile input that must never produce an action, and
a guard that fails if any module that resolves dates reads the system clock.

---

## Repository layout

```
backend/
  app/
    agent/      dates, clinical screen, extraction, Gemini adapter, policy engine, replies
    tools/      the six tools
    store.py    SQLite clinic state, seeded per request
    ui_store.py conversation log behind the two screens
  tests/        51 tests
  data/         clinic.json
frontend/       React, two screens and a shared sidebar
adversarial/    eight conversation scripts
conversations/  the 15 you shipped
runner.py       yours, unchanged
check.py        scores results against each script's `expected`
metrics_table.py generates the table above from real result files
DECISIONS.md    every ambiguity, what I chose, and why
```

---

## Known limitations

- The transcript lists caller turns, then tool calls, then the reply, rather than
  interleaving. That is the real order — the policy engine reads every turn
  before acting — and drawing a different one in the panel whose job is to prove
  nothing was invented seemed worse than the mismatch with the mockup.
- No tool registers a new patient, so a caller absent from `clinic.json`
  escalates as `out_of_scope` rather than being booked.
- The free Render tier sleeps after ~15 minutes idle, so the first request to the
  live link can take 30–60 seconds.

See `DECISIONS.md` for the twelve inconsistencies I found in the material, and
what I did about each.
