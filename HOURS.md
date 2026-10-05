# Hours log

| Date | Block | Hours | What |
|---|---|---|---|
| 2026-10-04 | Setup, tool layer, tests, endpoint | 6.0 | Repo, six tools, slot grid, name matching, SQLite store, 20-thread race test, contract-valid `/agent/run`, `check.py` |
| 2026-10-05 | Agent core, adversarial cases, UI | 7.5 | Date and time resolution, clinical screen, Gemini extraction with rule fallback, policy engine, eight adversarial cases, two React screens, conversation log |
| 2026-10-06 | Deploy, hardening, docs | 2.5 | Render and Vercel, Devanagari support, role-assignment fix, 138 tests, README and DECISIONS |

**Total: ~16 hours.**

The brief estimated 5 to 6. Most of the extra went on two things: reading
`clinic.json` closely enough to find the contradictions listed in DECISIONS.md,
and the eight adversarial cases, which found two real bugs in my own agent.
