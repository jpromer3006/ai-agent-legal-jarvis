# Prompt for Claude Code: JARVIS Cleanup 2 (hackathon scope)

Put `JARVIS_TEST_REPORT_ROUND2.md` in the project root, then paste everything below the line into Claude Code from `/Users/jpromero/Ai-agent Legal Jarvis/`.

---

You are an adversarial senior AI engineer finishing JARVIS Legal OS for a **legal hackathon**. It is an **educational prototype, not production**. Read `JARVIS_TEST_REPORT_ROUND2.md` in full first; it is the spec and contains live reproductions. Scope is P0 and P1 plus selected P2. Do not start the large refactors from the older review (encryption, full app.py split, CI) unless every item here is done.

## Ground rules
1. **Step 0: version control.** The folder is not a git repo. Run `git init`, confirm `.gitignore` covers `.env`, `.venv/`, `cases/`, `__pycache__/`, `.pytest_cache/`, then commit the current state as `baseline: pre cleanup 2`. Commit after each numbered section below.
2. Use the `dev2` conda env: `/Users/jpromero/anaconda3/envs/dev2/bin/python -m pytest -q`. The project `.venv` has no pytest; either install dev deps there or remove it, ask me which.
3. No live API calls in tests. Mock the Anthropic client. Live smoke tests go in `tests/live/`, skipped unless `JARVIS_LIVE=1`.
4. Legal rules live in `data/*.json` with `source_citation`, `source_url`, `needs_verification: true`, `reviewed_by: null`. Never invent or "correct" legal content yourself; list anything you think is wrong in the summary for me to verify.
5. Every bug fix starts with a failing test that reproduces it, taken from the report.
6. Ask before deleting files or changing theme colors.

## 1. P0 fixes (all required)
1. **P0.1 Crash:** replace regex plus `json.loads` in `_ask_json` with Anthropic tool use and a JSON schema (forced tool choice) for facts and classification. Add a `safe_call()` wrapper used by every Claude, ElevenLabs, and search call: timeout, one retry, logged error, friendly UI message. On classify failure fall back to `baseline_classify`. A test with malformed JSON and one with an API exception must pass with no traceback.
2. **P0.2 Resolver:** rewrite `resolve_mta_entity` as ordered word boundary regex rules, most specific first (LIRR, Metro North, Staten Island Railway, MTA Bus Company, then NYCT subway and bus by explicit phrases like "subway", "MTA bus", line letters with "train" only as "the A train"). Add a non MTA guard list (Amtrak, NJ Transit, PATH, gas station, police station, train station of another railroad). Return `None` when uncertain. Move the rule table into `data/mta_entities.json`. Tests: every probe in report Section 5 items 1 to 4 plus the 9 probes listed in P0.2.
3. **P0.3 Rejection:** add `entity_rejected` to `CaseFile`; after NOT CORRECT never auto resolve again; show a select box of known respondents plus "Other / not sure".
4. **P0.4 and P0.5 Next Step:** remove the domain only fallback in `find_first_step`. Always render research findings. Render the Next Step card next to them only on an exact (domain, respondent) match and only after the entity is confirmed. Otherwise show "No verified procedure on file for this respondent" plus help resources.
5. **P0.6 Vague dates:** `normalize_date` returns a result object `{iso, raw, confidence: exact|assumed|vague}`. `last week`, `last month`, `a while ago` are vague: no ISO date, Jarvis asks for the exact date, the deadline panel says "Exact date needed". Assumed year dates ask for confirmation.
6. **P0.7 Folders:** `CaseFile` creates its folder lazily on first `save()`; add a random 4 character suffix. Test: constructing 5 CaseFiles creates zero folders.

## 2. Speed and live agent view (report Sections 7 and 8)
Measure first: add timing logs per step and record a before table (intake answer, each agent, research total) in the final report.
1. **Parallel research:** run StatuteAgent and ContextAgent concurrently (ThreadPoolExecutor or `AsyncAnthropic`), then ValidatorAgent.
2. **Merged fast intake:** one structured output call per answer returning facts, timeline, and areas, on a model set by `JARVIS_FAST_MODEL` (default `claude-haiku-5-5`; check current Anthropic model ids). Keep `JARVIS_MODEL` (Sonnet) for research and IRAC. Reclassify only when narrative, location, or parties change.
3. **Prompt caching** on the guardrail, IRAC, and other fixed system prompts (check current Anthropic prompt caching docs).
4. **Prefetch:** once narrative, exact date, and a confirmed entity exist, start research in a background thread; RUN RESEARCH shows results immediately if done, or attaches to the in flight run.
5. **Result cache** keyed by (area, respondent, jurisdiction) with 24 h TTL in `cache/` (gitignored).
6. **Trim:** StatuteAgent 4 searches, ContextAgent 2, lower max_tokens; values in one config module.
7. **Live agent view:** use `client.messages.stream(...)`. Each agent thread pushes events to a `queue.Queue`: `state` changes, `search_query` (from `server_tool_use` blocks), `search_results` (from `web_search_tool_result`, with tier badges), `text_delta`, `citation`. The UI drains the queue in an `st.fragment(run_every=0.5)` and renders HUD styled agent cards (QUEUED, SEARCHING, READING, CITING, VALIDATING, DONE, with timers), a live query feed, sources appearing in the Source Authority panel, and a final validator line ("N consulted, N cited, N primary law"). Include a plain language narration line for pro se users. Keep the existing theme. Streamlit widgets must only be touched from the main script thread.
8. Write the after timing table next to the before table. Targets: intake under 4 s per answer, research under 30 s wall time.

## 3. P1 trust fixes
1. **Validator (lightweight claims ledger):** in `_search`, keep two lists: `cited` (from text block citations, with `cited_text`) and `consulted` (search results). Status and confidence use only `cited`. Store `cited_text` on each Source and show it on hover or expand in the Source Authority panel. Status rules: `verified` needs at least one cited T1 or T2 source with non empty `cited_text`; `partial` for cited T3; else `unsupported`. Demo findings must never say verified.
2. **Authority tiers:** remove `.us` from Tier 1 suffixes. URLs under `nysenate.gov/legislation/bills/` get a new label "LEGISLATIVE HISTORY" (weight 0.3), not primary law. `mtaig.ny.gov` is government but not primary law: label "GOVERNMENT, NON LEGAL". Tests for each.
3. **Classifier:** LLM prompt forbids citations in the "why" line. Baseline uses word boundary regex and phrases; add the four sentences from P1.4 as regression tests.
4. **Intent gate:** before slot filling, detect questions and advice requests (start with a rule list: should I, will I win, how much, do I need a lawyer, write my, plus a `?` check; LLM intent label when online). Response: short information only reply plus help resources, then re ask the pending question. Not stored as a fact.
5. **Dates:** support "October 14", "10/14", "Sept 30, 2026", word numbers ("two days ago"), fix "the day before yesterday" (minus 2), reject future dates, flag two digit years.
6. **Rollover:** `compute_deadline` applies weekend and holiday rollover from `data/ny_holidays.json` (2026 and 2027) with `rule_citation: "NY Gen. Constr. Law § 25-a"`, `needs_verification: true`. Result includes `rolled_from` when adjusted; UI shows it.
7. **Lawyer Mode:** change IRAC section IV to "Possible outcomes, open questions, and further research needed". Replace the privilege stamp with "EDUCATIONAL DEMO, NOT LEGAL ADVICE" (configurable). Keep the web search sources the memo call returns (currently discarded) and append them to SOURCES.
8. **Fake case check:** add `sources/courtlistener.py` with citation lookup (check current CourtListener v4 API docs for the endpoint, token from `COURTLISTENER` env). In Lawyer Mode, extract case citations from the memo and mark each VERIFIED or NOT FOUND in a table under the memo and in the PDF. Use a recorded fixture in tests.
9. **Statute text (stretch):** `sources/openlegislation.py` fetches section text for cited NY sections (check current API docs for law ids) and shows it in an expander with the retrieval date.

## 4. P2 demo polish
1. `JARVIS_USER` default becomes "GUEST".
2. (Covered by the live agent view in Section 2.)
3. RUN RESEARCH disabled until narrative, an exact date, and location exist.
4. Accessible names on all buttons.
5. Educational disclaimer from report Section 10 on the consent gate, under every findings panel, in the PDF footer, and appended to the spoken summary.
6. `data/help_resources.json` (NYC Court Help Centers, LawHelpNY, Legal Aid Society, NYC Bar Legal Referral Service, CourtHelp) shown with findings, `needs_verification: true`.

## 5. Tests and eval
1. `tests/adversarial/` implementing report Section 5 items 1 to 24 with mocks.
2. `evals/classifier_gold.jsonl`: 60 synthetic fact patterns (5 per area, half English half Spanish), and `evals/run_classifier_eval.py` printing per area precision, recall, macro F1 and saving a confusion matrix PNG to `reports/eval/`. Keyword baseline offline; LLM mode only with `JARVIS_LIVE=1`.
3. `streamlit.testing.v1.AppTest` smoke tests: consent gate blocks intake; reload creates no folders; malformed model output shows a friendly message.

## 6. Visual overview
1. `docs/architecture.md` with Mermaid: module map, intake to research sequence, Pro Se and Lawyer Mode flow, validator decision tree.
2. Update README: run steps, data flow (Anthropic, ElevenLabs, browser speech recognition), educational disclaimer, list of unverified legal data.

## 7. Finish
1. Run the full suite and the classifier eval.
2. Start the app on port 8502 and report it is up.
3. Write `reports/CLEANUP_2_REPORT.md`: each report item with status (fixed, partial, deferred) and the test that proves it, before and after test counts, before and after latency table, eval scores, and **a list of legal data items awaiting my verification** (show that list first).
