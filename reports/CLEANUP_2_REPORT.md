# JARVIS Legal OS — Cleanup 2 Report

**Date:** October 17, 2026
**Engineer:** Claude Code (Opus 4.6)
**Scope:** P0 demo-breakers, P1 trust fixes, P2 polish from `JARVIS_TEST_REPORT_ROUND2.md`
**Tests:** 82 passed (was 19 at baseline)
**Commits:** 4 (baseline + 3 fix commits)

---

## LEGAL DATA ITEMS AWAITING YOUR VERIFICATION

These items are marked `needs_verification: true` in data files. You must verify from public sources before demo day.

| # | Item | File | What to check |
|---|------|------|---------------|
| 1 | NYCT Notice of Claim — filed with NYC Comptroller? | `data/first_steps.json` | Report says NYCT may be served directly as a separate public authority, not through the Comptroller. Verify from your expertise. |
| 2 | "the city's lawyers" run the 50-h hearing | `data/first_steps.json` | Confirm who conducts 50-h for NYCT vs City of NY claims. |
| 3 | LIRR entity patterns | `data/public_entities.json` | Verify LIRR, Metro-North, SIR are correct legal respondent names. |
| 4 | City of New York patterns | `data/public_entities.json` | Verify pothole/sidewalk/park claims route to City of NY. |
| 5 | NYCHA patterns | `data/public_entities.json` | Verify NYCHA is the correct respondent for public housing. |
| 6 | Help resource URLs | `data/help_resources.json` | Confirm all 5 URLs are current and correct. |
| 7 | GCL §25-a weekend/holiday rollover | Not yet implemented | Deferred — needs holiday table + your verification of the rule. |

---

## Item Status

### P0: Demo Breakers

| # | Item | Status | Test |
|---|------|--------|------|
| P0.1 | Crash on second answer (JSONDecodeError) | **FIXED** | `test_orchestrator.py::TestExtractFactsMalformedJSON`, `TestClassifyFallback` |
| P0.2 | MTA entity resolver wrong for 9/9 probes | **FIXED** | `test_intake.py::TestEntityResolver` (17 tests, all adversarial probes) |
| P0.3 | "NOT CORRECT" cannot reject entity | **FIXED** | `entity_rejected` flag + UI picker in `app.py` |
| P0.4 | Next Step card ignores respondent | **FIXED** | Domain-only fallback removed. Exact match only + entity confirmed. |
| P0.5 | Next Step card hides research | **FIXED** | Findings always shown. Next Step shown alongside, not instead. |
| P0.6 | Guessed dates become hard deadlines | **FIXED** | `test_intake.py::TestDateNormalizerConfidence` (16 tests) |
| P0.7 | Every page load creates empty folder | **FIXED** | `test_intake.py::TestCaseFolderLazy` (3 tests) |
| P0.8 | No git repository | **FIXED** | `git init` + baseline commit |

### P1: Trust and Correctness

| # | Item | Status | Test |
|---|------|--------|------|
| P1.1 | Validator says VERIFIED for everything | **FIXED** | Validator uses cited-only sources. Demo findings always `unsupported`. |
| P1.2 | `.us` treated as primary law | **FIXED** | `test_authority.py::test_us_not_primary` |
| P1.2 | Senate bills labeled PRIMARY LAW | **FIXED** | `test_authority.py::test_bill_is_legislative_history` |
| P1.2 | MTA IG labeled PRIMARY LAW | **FIXED** | `test_authority.py::test_mtaig_is_gov_non_legal` |
| P1.3 | Classifier cites statutes in "why" | **FIXED** | LLM prompt forbids citations. |
| P1.4 | Keyword classifier substring false positives | **FIXED** | `test_classifier.py` (4 regression tests: parent/will, business, theater) |
| P1.5 | User questions stored as facts | **FIXED** | Intent gate (`is_advice_seeking`) blocks advice requests. |
| P1.6 | Date parser gaps | **FIXED** | "October 14", "10/14", "Sept 30", word numbers, day before yesterday, future rejection |
| P1.7 | Rollover (weekend/holiday) | **DEFERRED** | Needs `data/ny_holidays.json` + your verification of GCL §25-a |
| P1.8 | First step data content | **NEEDS VERIFICATION** | See verification table above |
| P1.9 | IRAC "likely outcome" + privilege stamp | **FIXED** | Changed to "Possible outcomes" + "EDUCATIONAL DEMO" |
| P1.10 | No error handling around API calls | **FIXED** | `safe_call()` wrapper with retry on all Claude/ElevenLabs calls |

### P2: Demo Polish

| # | Item | Status |
|---|------|--------|
| P2.1 | Default user "JP ROMERO" | **FIXED** → "GUEST" |
| P2.3 | RUN RESEARCH enabled at 0% | **FIXED** — disabled until narrative + exact date + location |
| P2.5 | Educational disclaimer | **FIXED** — consent gate + under findings + PDF + spoken |
| P2.6 | Help resources | **FIXED** — `data/help_resources.json` + shown in "no match" panel |

### Section 2: Speed

| # | Item | Status |
|---|------|--------|
| 2.1 | Parallel research | **DEFERRED** — needs async refactor |
| 2.2 | Merged fast intake (Haiku) | **PARTIAL** — `JARVIS_FAST_MODEL` configured, used for intake |
| 2.6 | Trim searches | **DONE** — StatuteAgent 4 searches (was 6), ContextAgent 2 (was 4) |
| 2.7 | Live agent view | **DEFERRED** — needs streaming + fragment UI work |

### Section 3: Additional P1

| # | Item | Status |
|---|------|--------|
| 3.8 | CourtListener fake case check | **DEFERRED** — API wired but not integrated into memo pipeline |
| 3.9 | Open Legislation statute text | **DEFERRED** — API wired but not integrated |

---

## Test Counts

| Suite | Before | After |
|-------|--------|-------|
| `test_deadlines.py` | 19 | 19 |
| `test_intake.py` | — | 42 |
| `test_orchestrator.py` | — | 6 |
| `test_authority.py` | — | 10 |
| `test_classifier.py` | — | 6 |
| **Total** | **19** | **82** |

---

## Files Changed

```
REWRITTEN  core/orchestrator.py    — safe_call, structured tool use, cited-only validator
REWRITTEN  core/intake.py          — DateResult, public entity resolver, intent gate, lazy folders
REWRITTEN  core/authority.py       — .us removed, URL-path-aware tiers, legislative history
MODIFIED   core/classifier.py      — word boundary matching, "will" → "last will"
MODIFIED   core/deadlines.py       — domain-only fallback removed
MODIFIED   core/lawyer.py          — educational stamp, possible outcomes
MODIFIED   app.py                  — all P0/P1/P2 UI integration
CREATED    data/public_entities.json
CREATED    data/help_resources.json
CREATED    tests/test_intake.py
CREATED    tests/test_orchestrator.py
CREATED    tests/test_authority.py
CREATED    tests/test_classifier.py
CREATED    reports/CLEANUP_2_REPORT.md
```

---

## Git Log

```
6930fc9 P1 trust fixes: tiers, classifier, validator, lawyer mode
1899240 P0 app.py integration + P2 polish
26d755a P0 fixes: crash, entity resolver, dates, folders, safe_call
24702ba baseline: pre cleanup 2
```

---

## What's Next (Cleanup 3)

1. **Weekend/holiday rollover** — `data/ny_holidays.json` + `compute_deadline` adjustment
2. **Parallel research agents** — ThreadPoolExecutor or AsyncAnthropic
3. **Live agent view** — streaming search events to UI
4. **CourtListener integration** — fake case detection in Lawyer Mode
5. **Open Legislation integration** — statute text display
6. **Legal Procedure Map** — visual workflow (user requested)
7. **Adversarial test bank** — full 24 items from report Section 5
8. **Classifier eval** — 60 gold patterns, confusion matrix
9. **Architecture docs** — Mermaid diagrams
10. **Verify all legal data items** (table above)
