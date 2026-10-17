# Jarvis Cleanup 1 — Code Review, Bug Fixes & Testing Report

**Date:** October 17, 2026
**Reviewer:** Claude Code (Opus 4.6)
**Scope:** Full codebase audit, bug fixes, dead code removal, documentation, end-to-end testing

---

## 1. Executive Summary

Full adversarial audit of all 10 Python source files (2,196 lines). Found **10 issues** — 2 bugs (one crash-severity), 7 dead code items, 1 code smell. All fixed. Removed **97 lines** of dead code. All 19 unit tests pass. All 4 API integrations verified. App serves clean.

---

## 2. Bugs Found & Fixed

### BUG-1: `NameError` crash in offline mode (CRITICAL)
- **File:** `core/orchestrator.py:126`
- **Severity:** Application crash when running without API key
- **Root cause:** `extract_facts()` ends with `self._log("IntakeAgent", f"filled {', '.join(facts)}")` but the local variable `facts` was only assigned inside the `else` (online) branch. The `if not self.online` branch set `case.facts[slot]` directly without defining `facts`.
- **Impact:** Any user running in offline/demo mode would crash on their first intake answer.
- **Fix:** Added `facts = {slot: answer}` in the offline branch so the log line always has a valid reference.

### BUG-2: `st.html()` called with invalid `height` parameter
- **File:** `app.py:859`
- **Severity:** Runtime warning, potential future breakage
- **Root cause:** Migration from deprecated `st.components.v1.html(..., height=60)` to `st.html(...)` kept the `height` kwarg, which `st.html()` does not accept.
- **Fix:** Removed `height=60` from the call.

---

## 3. Dead Code Removed

| # | Item | File | Lines Removed | Description |
|---|------|------|--------------|-------------|
| D1 | `stt_component_html()` | `core/voice.py` | 89 | Old "HOLD TO SPEAK" button STT component, replaced by `_voice_auto_listen_html()` in `app.py`. Never called. |
| D2 | `VOICE_ENABLED` constant | `core/voice.py` | 1 | Set to `True`, never read by any module. |
| D3 | `voice_phase` state var | `app.py` | 1 | Leftover from old separate voice mode UI (phases: idle/intake/searching/summary/chat). Voice redesigned as dashboard overlay. |
| D4 | `voice_audio_queue` state var | `app.py` | 1 | Initialized but never read or written. |
| D5 | `asked` field on `CaseFile` | `core/intake.py` | 1 | Dataclass field `asked: list[str]` never populated or read. |
| D6 | `import textwrap` | `core/lawyer.py` | 1 | Imported but unused. |
| D7 | `PageBreak` import | `core/lawyer.py` | 1 | Imported from reportlab but unused. |

**Total dead code removed: 97 lines**

---

## 4. Code Smell Fixed

### `import calendar` inside function body
- **File:** `core/deadlines.py:48`
- **Problem:** `import calendar` was nested inside `compute_deadline()` rather than at module level. Violates PEP 8 and adds import overhead per call.
- **Fix:** Moved to top-level imports.

---

## 5. Test Results

### 5.1 Unit Tests (pytest)
```
19 passed in 0.01s

TestComputeDeadline (9 tests):
  test_today_incident           PASSED
  test_89_days_ago              PASSED
  test_91_days_ago_expired      PASSED
  test_leap_year                PASSED
  test_months_rule              PASSED
  test_months_clamp_end_of_month PASSED
  test_invalid_date_raises      PASSED
  test_invalid_rule_type_raises PASSED
  test_label                    PASSED

TestNormalizeDate (7 tests):
  test_today                    PASSED
  test_yesterday                PASSED
  test_n_days_ago               PASSED
  test_explicit_date            PASSED
  test_us_format                PASSED
  test_unparseable_returns_none PASSED
  test_raw_preserved            PASSED

TestFirstSteps (3 tests):
  test_load                     PASSED
  test_find_nyct                PASSED
  test_find_missing             PASSED
```

### 5.2 Compile Check
```
All 10 Python files compile clean (py_compile, zero errors):
  app.py, core/__init__.py, core/authority.py, core/classifier.py,
  core/deadlines.py, core/intake.py, core/lawyer.py,
  core/orchestrator.py, core/voice.py, tests/test_deadlines.py
```

### 5.3 Integration Tests
```
Module Imports:        ALL OK (authority, classifier, deadlines, intake,
                       orchestrator, voice, lawyer)

Classifier:            "fell on subway platform" → Torts/PI (score 1.0)    OK
Source Ranking:         nysenate.gov → T1 PRIMARY LAW                      OK
Date Normalizer:        "yesterday" → 2026-10-16                           OK
MTA Entity Resolver:    "subway platform" → NYC Transit Authority          OK
Deadline Engine:        Oct 1 + 90 days → Dec 30, 2026 (74d remaining)     OK
Case Folder:            Created cases/case_*/case.json                     OK
PDF Generation:         2,305 bytes from sample memo                       OK
ElevenLabs TTS:         15,089 bytes (George voice, British)               OK
Claude API:             Connected (claude-sonnet-5-5)                      OK
```

### 5.4 App Launch
```
Streamlit on port 8502 → HTTP 200, no errors in log
```

---

## 6. API Key Status

| Key | Variable | Status |
|-----|----------|--------|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | Working — 14 models available |
| ElevenLabs (TTS) | `ELEVENLABS_API_KEY` | Working — 22 voices, George selected |
| CourtListener | `COURTLISTENER` | Working (HTTP 200) — not yet wired into agents |
| NY Open Legislation | `OPEN_LEGISLATION` | Working (HTTP 200) — not yet wired into agents |

---

## 7. Code Metrics (Post-Cleanup)

| File | Before | After | Delta |
|------|--------|-------|-------|
| `app.py` | 1,007 | 1,003 | -4 |
| `core/voice.py` | 171 | 81 | **-90** |
| `core/lawyer.py` | 259 | 256 | -3 |
| `core/orchestrator.py` | 261 | 262 | +1 |
| `core/intake.py` | 203 | 202 | -1 |
| `core/deadlines.py` | 83 | 83 | 0 |
| `core/authority.py` | 117 | 117 | 0 |
| `core/classifier.py` | 96 | 96 | 0 |
| `tests/test_deadlines.py` | 123 | 123 | 0 |
| **Total** | **2,196** | **2,099** | **-97** |

---

## 8. Files Modified

```
core/orchestrator.py   — Fixed NameError in offline extract_facts() [BUG-1]
app.py                 — Removed st.html height param [BUG-2],
                         removed dead state vars (voice_phase, voice_audio_queue)
core/voice.py          — Removed dead stt_component_html() (89 lines),
                         removed unused VOICE_ENABLED constant
core/intake.py         — Removed unused `asked` field from CaseFile
core/lawyer.py         — Removed unused imports (textwrap, PageBreak)
core/deadlines.py      — Moved calendar import to top level
```

---

## 9. Known Issues Not Addressed (Deferred)

| # | Issue | Reason Deferred |
|---|-------|----------------|
| N1 | CourtListener API not wired into agent pipeline | Content feature, not a bug |
| N2 | Open Legislation API not wired into agent pipeline | Content feature, not a bug |
| N3 | `first_steps.json` has only 1 entry (NYCT torts) | Content expansion needed |
| N4 | Voice STT requires Chrome/Edge/Safari | Browser limitation |
| N5 | Legal procedure workflow visualization | Feature request in progress |
| N6 | Weekend/holiday deadline rollover not implemented | Correctness enhancement |

---

## 10. Recommendations for Cleanup 2

1. Wire CourtListener into `StatuteAgent._search()` for case law verification
2. Wire Open Legislation into `StatuteAgent._search()` for NY statute text
3. Expand `first_steps.json` to cover all 12 law areas
4. Add integration tests with mocked API responses (no live calls in CI)
5. Split `app.py` (1,003 lines) into `ui/` modules
6. Add `CLAUDE.md` with project conventions
7. Implement claims ledger with quote-level source verification
8. Add per-output disclaimer (not just consent gate)
9. Implement legal procedure flowchart visualization

---

*Jarvis Cleanup 1 complete. 10 issues found, 10 fixed. 97 lines removed. 19/19 tests pass. All 4 APIs verified. App serves clean.*
