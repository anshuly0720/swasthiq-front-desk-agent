# Decisions

Every ambiguity I found, what I chose, and why. The inconsistencies come first
because the brief asks for them explicitly.

Dates resolve against the `today` field in each request. Nothing in this
project reads the system clock.

## What I think is wrong or inconsistent in the material you gave me

1. **"Two doctors and two appointment windows per day each" is false in the data.**
   Dr. Rao has one window on Saturday and none on Sunday; Dr. Sethi has one on
   Wednesday, one on Saturday, none on Sunday. I built the slot grid from the
   windows actually present, not from the stated rule.

2. **Dr. Rao's Monday windows overlap:** 09:00–12:00 and 11:45–15:00. Generating
   slots per window yields 25 with 11:45 appearing twice; the real grid is 24.
   This is not a typo for 16:00–19:00, because ap_0010 (Mon 5 Oct, 13:00) only
   fits inside the second window. I de-duplicate by taking the union of the day's
   windows. Consequence: Dr. Rao has no evening slots on Mondays.

3. **The example response in schema.md violates the contract's own rules.** Its
   turns say "Kal subah" against today = 2026-10-01, but it books 2026-10-03
   (kal is 2026-10-02, the clinic holiday). It returns patient_id pt_0014 with no
   lookup_patient call and no caller identity in the turns. It is labelled
   cv_0001, but the real cv_0001 has different turns and a different caller —
   Harpreet Singh is pt_0013; pt_0014 is Harpreet Kaur. I treated the field table
   as normative and the worked example as illustrative only.

4. **The Conversation Detail mockup shows an ungrounded patient.** It displays
   patient_id pt_0192, outside the pt_0001–pt_0040 range, with two tool calls,
   neither of them lookup_patient. It also writes doctor_id "d_rao" where the
   data says "dr_rao", and shows turns = 6 for two caller utterances. I matched
   the mockup's layout and copy, but my UI only renders IDs that came from a tool.

5. **The paediatrician sees adults.** Six of Dr. Sethi's nine shipped
   appointments are for patients aged 25–60. So speciality cannot be a booking
   constraint, and I do not enforce one.

6. **Per-run reset contradicts the race requirement.** README.md and schema.md
   say every POST /agent/run starts from clinic.json as shipped; the brief says
   two conversations racing for one slot must not both succeed. Under a per-run
   reset two graded runs can never race. I enforce the guarantee at the storage
   layer — a partial unique index on (doctor_id, date, start) over active
   appointments — so it holds for any concurrent callers against one store,
   proved by a 20-thread test in backend/tests/test_race.py.

7. **"Two example scripts deliberately book the same slot" (README) — I could not
   find the pair.** The three scripts landing on Dr. Rao's Saturday ask for
   "subah" (cv_0001), 10:00 (cv_0003, a reschedule) and 11:00 (cv_0012).

8. **No time of day exists anywhere.** Requests carry a date only. cv_0003 and
   cv_0004 act on "aaj ka appointment" at 09:30 and 10:00 with no way to know
   whether those have passed. I therefore treat every slot on `today` as
   bookable and never reject one as already elapsed.

9. **Two capability gaps in the tool list.** Nothing registers a new patient, so
   a caller absent from clinic.json cannot be booked without inventing a record
   — I escalate those as out_of_scope. And nothing lists a patient's
   appointments, yet cancel and reschedule need an appointment ID that must have
   come from a tool. Rather than add a seventh tool and break the fixed set you
   match on, I extended lookup_patient to return each candidate's active
   appointments alongside their guardian links.

10. **Confidential brief, public repository.** The PDF says do not share or
    publish; the submission guidelines require a public repo that cannot run
    without the starter files. I kept the repo private during development and
    made it public only at submission, and excluded the PDF itself.

11. **Two submission channels.** The PDF asks for an email with three links; the
    portal has its own form with no video field and is final once submitted.
    I did both, email first.

12. **clinic.reference_date vs the request's today.** Both are 2026-10-01 in
    every example. I resolve all dates against the request's `today` and ignore
    reference_date entirely, per schema.md.

### Traps I read as deliberate, not errors

- cv_0011: "kal" is 2026-10-02, the clinic holiday, so no 10:00 slot exists even
  before the clinical turn arrives.
- Three patients share phone 9812200166 (Aarav, Arjun, Sunita Gupta); two share
  9812200197 (Meera, Kabir Joshi); two share 9812200466 (Sanjay, Kavita Rawat).
  The Rawats have no guardian link, so a shared phone is not authorisation.
- Only two guardian links exist: Sunita Gupta → Aarav, Arjun; Meera Joshi → Kabir.
- "Imran Qureshi" (pt_0010) and "Imraan Quraishi" (pt_0011) are different people
  whose names are phonetically identical.
- Shared first names: Rajesh ×2, Priya ×2, Harpreet ×2. Shared surnames:
  Sharma ×3, Gupta ×3, Joshi ×2, Rawat ×2.

## Decisions I made
### The transcript shows tool calls after the turns, not between them

The mockup interleaves tool calls with the conversation. Mine lists the caller's
turns, then the tool calls, then the agent's reply, because that is the real
order: the policy engine reads every turn before it calls a mutating tool, so a
clinical red flag in the final turn arrives before a booking could commit.
Drawing the calls between the turns would show an order that did not happen, in
the one panel whose whole job is to prove nothing was invented.

### Model, quota and what happens when it runs out

gemini-2.5-flash, pinned. gemini-2.0-flash was retired during this assignment
and gemini-3.8-flash returns RESOURCE_EXHAUSTED on a free key, so I probed the
models the key can actually serve rather than trusting a name.

Free-tier quota is finite and the hidden set is ~25 conversations run 3 times.
Three things follow: calls are paced (LLM_MIN_INTERVAL), identical prompts are
cached on disk (LLM_CACHE=0 disables it, and the determinism figures below were
measured with it off), and when the model is unreachable the rule-based
extractor takes over rather than the conversation failing. All 23 of my test
cases pass on rules alone — the model raises the ceiling on phrasings the rules
do not cover; it is not load-bearing for correctness.
### Architecture: the model interprets, code decides

**The model never chooses a tool, emits an identifier, or does date arithmetic.**
It extracts structured intent from each turn; a Python policy engine decides
which tools fire, with what arguments, in what order.

Reason: schema.md scores determinism on the *set of tool names* across three
runs, and a model free to choose tools will not produce the same set three times.
The same property makes prompt injection structurally inert — there is no path
from caller text to a mutating call. And it makes "zero invented facts" true by
construction rather than by instruction, because every identifier in a reply was
returned by a tool.

Cost of this choice: less "agentic" in the demo sense, and the policy engine
is where the complexity moves. I think that is the right trade for a healthcare
front desk, where the failure mode is a confident wrong action.

### Tool layer is LLM-free

Nothing under backend/app/tools imports a model client. The tool layer is the
ground truth the agent is checked against, so it cannot depend on the thing
being checked.

### Mutations happen only after the final turn

Read-only tools fire as soon as their inputs exist. book, reschedule and cancel
run only once every turn has been read. This is what makes the hard rule
structural: a clinical red flag in any turn always arrives before any booking
could commit, including when it lands in the last turn.

### Repository visibility

Kept private during development, made public at submission, because the brief
marks the material confidential and also requires a public repository.

### Latency is measured server-side

The runner's client-side wall clock reported ~2,040 ms per conversation against
a stub whose own measurement was 1 ms. The constant was Windows resolving
`localhost` to IPv6 first while uvicorn listens on IPv4; calling 127.0.0.1
directly gives 70 ms. The figures in README.md are the server-side `metrics`
values, because the client number measured my laptop's resolver, not the agent.1



### Who is calling versus who the appointment is for

The hardest part of this data is that the clinic records make identity genuinely
ambiguous: Aarav and Arjun Gupta share a surname, a date of birth and a phone
number, and Sanjay and Kavita Rawat share a number with no guardianship between
them. Two bugs here were found by my own adversarial cases rather than by
reading the code.

The first: a name with no marker beside it claimed the caller slot, so the real
caller could not take it, subject and caller resolved to the same person, and
the guardianship check never ran. `adv_0004` cancelled a man's appointment for
his wife. Evidence is now assigned first, and an unmarked name only fills a role
still empty.

The second: markers were tested as a yes/no proximity window. In
"Main Sunita Gupta, 9812200166, Aarav ke liye" both a caller marker and a
subject marker are within reach of both names, so neither could be separated and
the booking went to the guardian. Roles are now assigned by *nearest* marker.

Related: a name window may not cross punctuation or a run of digits. Stripping
digits out of the word list made "Gupta" and "Aarav" adjacent, so one window
spanned two different patients. A phone number between two names separates them.

### Devanagari input

The brief says callers speak Hindi, English and a mix, but all 15 example
scripts are romanised. Dates, weekdays, times, parts of day and the two doctors'
surnames are matched in Devanagari as well, and Devanagari digits are folded to
ASCII so the numeric rules are written once rather than twice. Without this, a
caller typing in Hindi script got `abandoned` instead of a booking -- safe, but
wrong.

### Two .env files, and which one wins

`load_dotenv()` walks up from the working directory and stops at the first file
it finds. A second `.env` in `backend/` holding one unrelated setting shadowed
the one at the repository root that held the key, and the agent silently ran on
rules with `metrics.source` reporting the fallback. There is now exactly one
`.env`, in `backend/`, and it is the only location documented. The incident is
the reason `metrics.source` is in the response at all: a model that quietly
stops being used should be visible in the output, not just in a log line.

### A test file that never ran

`tests/slots` was committed as `tests.slots.py`, which pytest does not collect,
so fourteen tests covering the slot grid had never executed. Renaming it
surfaced a second problem: the guard that forbids reading the system clock now
failed on `ui_store.py`, which timestamps conversation log entries. That is a
legitimate use -- a record of when a call actually happened, not a date derived
from the caller's words -- so the guard excludes that one file by name, and a
second test asserts the guard still covers every module that resolves dates.

### Still open

(append as they come up — do not batch these at the end)

