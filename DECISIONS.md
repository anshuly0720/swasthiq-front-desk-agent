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



### Still open

(append as they come up — do not batch these at the end)

