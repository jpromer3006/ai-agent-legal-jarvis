# JARVIS Legal OS — Full Project Report

**Generated:** October 17, 2026
**Author:** Claude Code (Opus 4.6)
**Project Location:** `/Users/jpromero/Ai-agent Legal Jarvis/`

---

## 1. Project Overview

JARVIS Legal OS is an AI-powered legal information system built with Streamlit. It provides a holographic Iron Man-style dashboard that guides users through legal intake, classifies their situation across 12 areas of law, searches official government and court sources, computes filing deadlines, and delivers cited findings — all without giving legal advice.

The system has two modes:
- **JARVIS Mode** — client-facing intake + research with voice support
- **Lawyer Mode** — attorney-facing IRAC memo generation with Claude Legal research

---

## 2. Architecture

```
Ai-agent Legal Jarvis/
  app.py                 (1,006 lines)  — Streamlit dashboard, all UI
  core/
    __init__.py           (0 lines)     — package marker
    authority.py          (117 lines)   — source tier ranking (T1-T5)
    classifier.py         (96 lines)    — law area classifier (keyword + LLM)
    deadlines.py          (83 lines)    — deadline computation engine
    intake.py             (203 lines)   — case file, question queue, date normalizer, MTA resolver
    lawyer.py             (259 lines)   — Lawyer Mode: IRAC memo, Claude Legal chat, PDF export
    orchestrator.py       (261 lines)   — agent orchestrator (5 agents), Claude API integration
    voice.py              (171 lines)   — ElevenLabs TTS + Web Speech API STT
  data/
    first_steps.json                    — procedural knowledge base (notice of claim steps)
  cases/                                — auto-created case folders with case.json
  tests/
    test_deadlines.py     (123 lines)   — unit tests for deadlines + date normalizer
  assets/
    jarvis_icon.png                     — app icon
    jarvis_icon.ico                     — Windows icon
  launchers/
    JARVIS.command                      — macOS double-click launcher
    JARVIS.bat                          — Windows launcher
    make_mac_app.sh                     — creates macOS .app bundle
  .streamlit/config.toml               — dark holographic theme config
  .env                                  — API keys (gitignored)
  .env.example                          — template for .env
  .gitignore
  requirements.txt
  README.md

Total source: 2,196 lines of Python across 10 files
Environment: Python 3.11, conda env `dev2`
```

---

## 3. API Keys & External Services

| Key | Service | Purpose | Status |
|-----|---------|---------|--------|
| `ANTHROPIC_API_KEY` | Claude API (Sonnet 5.5) | LLM for intake extraction, classification, research, IRAC memos | Working |
| `ELEVENLABS_API_KEY` | ElevenLabs TTS | Voice output (George, British male, Turbo v2.5 multi-language) | Working |
| `COURTLISTENER` | CourtListener API | Case law search (available, not yet wired into agents) | Working |
| `OPEN_LEGISLATION` | NY Open Legislation API | NY state bill/statute lookup (available, not yet wired) | Working |

---

## 4. Features — Detailed Breakdown

### 4.1 Consent Gate
- 5-line disclaimer in large bright text
- User must acknowledge before proceeding
- No data collected until consent given

### 4.2 Intake System (`core/intake.py`)
- **8 core questions:** narrative, when, where, who, harm, evidence, actions taken, goal
- **Area-specific follow-ups:** up to 3 extra questions per detected law area (e.g., "Was a government agency involved?" for torts)
- **Smart slot filling:** with Claude online, one answer can fill multiple slots simultaneously
- **Date normalizer:** parses "yesterday", "3 days ago", "10/14/2026", ISO formats
- **MTA entity resolver:** maps "subway", "J train", "LIRR" etc. to the correct legal respondent (e.g., "New York City Transit Authority")
- **Progress tracking:** percentage bar showing intake completion

### 4.3 Law Area Classifier (`core/classifier.py`)
- **12 law areas:** Torts, Workers Comp, Immigration, Criminal, Housing, Employment, Family, Consumer/Debt, Contracts, Civil Rights, Estates, Traffic
- **Two-layer classification:**
  1. Fast keyword baseline (always works offline)
  2. Claude LLM refinement with reasoning (when online)
- Displays top 3 areas with confidence scores and explanation

### 4.4 Source Authority Ranking (`core/authority.py`)
- **5-tier system:**
  - T1 PRIMARY LAW (weight 1.0): .gov, courts, municipal codes
  - T2 LEGAL SECONDARY (weight 0.75): Cornell LII, Justia, CourtListener, bar associations
  - T3 NEWS (weight 0.45): Reuters, NYT, Bloomberg
  - T4 COMMUNITY (weight 0.15): YouTube, Reddit, social media
  - T5 UNVERIFIED (weight 0.05): everything else
- Confidence score computed from source weights with corroboration bonus
- Sources deduped and sorted by tier

### 4.5 Research Agents (`core/orchestrator.py`)
Five specialized agents orchestrated by the Orchestrator:

| Agent | Role | Search Scope |
|-------|------|-------------|
| **IntakeAgent** | Extracts facts, normalizes dates, resolves entities | Local (Claude) |
| **ClassifierAgent** | Identifies law areas with reasoning | Local (Claude) |
| **StatuteAgent** | Searches primary law: statutes, regulations, codes | .gov, courts, code libraries (6 web searches) |
| **ContextAgent** | Finds guides, news, explainer videos | Open web (4 web searches) |
| **ValidatorAgent** | Checks every finding against source tiers | Local analysis |

- Uses Claude's `web_search_20250305` tool with domain restrictions
- StatuteAgent locked to 18 trusted legal domains
- Full offline demo mode when no API key is set

### 4.6 Deadline Engine (`core/deadlines.py`)
- Computes filing deadlines from incident date + rule (days or months)
- Handles leap years and month-end clamping (Jan 31 + 1 month = Feb 28)
- Returns: deadline date, days remaining, expired flag, human-readable label
- Knowledge base: `data/first_steps.json` with procedural steps per (domain, respondent) pair
- Currently 1 entry: Notice of Claim for NYCT (90-day deadline, 5 steps, 4 citations)

### 4.7 Voice Mode (`core/voice.py` + `app.py` overlay)
- **TTS:** ElevenLabs API, "George" voice (British, warm storyteller), model `eleven_turbo_v2_5`
- **4 languages:** English, Spanish, Mandarin, Hindi — all with the same British Jarvis accent
- **Translation:** non-English languages auto-translated by Claude before TTS
- **STT:** Browser Web Speech API (Chrome/Edge/Safari), continuous listening, auto-submit after 1.5s silence
- **Hands-free:** no buttons to press — auto-listens, auto-submits, auto-speaks
- **Language dropdown:** centered under hologram in voice mode
- **"VOICE MODE OFF"** button in red to deactivate
- **Dedup:** spoken keys include language, so switching language re-speaks in new language

### 4.8 Lawyer Mode (`core/lawyer.py` + `app.py`)
- **Gold "LAWYER MODE" button** in top-right corner
- **Jarvis transfers:** all case facts, research findings, and sources carried over
- **Claude Legal chat:** attorney can discuss prior cases, request additional research, refine analysis — all with web search enabled (5 searches per query)
- **IRAC Memo generation:**
  - Issue(s) Presented
  - Rule(s) of Law
  - Application to facts
  - Conclusion with recommended action
  - Sources section with numbered footnotes `[1]`, `[2]` and clickable URLs
- **PDF download:** professional legal memo format via ReportLab
  - "PRIVILEGED AND CONFIDENTIAL — ATTORNEY WORK PRODUCT" header
  - Times New Roman, justified text
  - Clickable footnote links
  - Auto-named: `IRAC_Memo_YYYYMMDD_HHMM.pdf`
- **Chat history feeds memo:** prior discussion with Claude Legal is included as context
- Memo also saved to case folder as `irac_memo.txt`

### 4.9 Case Folder System (`core/intake.py`)
- Each new case creates `cases/case_YYYY-MM-DD_HH-MM-SS/`
- `case.json` auto-saved after each intake answer and after research
- Contains: facts, areas, timeline, transcript, dates, entity resolution
- IRAC memo saved alongside as `irac_memo.txt`
- `cases/` directory is gitignored

### 4.10 Holographic Dashboard (`app.py`)
- **3-column layout:** Left (intake + facts + timeline), Center (reactor SVG + controls), Right (sources + agent log)
- **Animated reactor SVG:** spinning rings, pulsing triangle, progress arc
- **Dark theme:** custom CSS with Orbitron + Share Tech Mono fonts, cyan/neon palette
- **Status indicators:** AWAITING ACCOUNT → LISTENING → RESEARCH READY → FINDINGS DELIVERED
- **First Step panel:** deadline countdown, step-by-step instructions, citations, respondent info
- **Transcript expander:** full conversation history

---

## 5. UI Theme & Design

- **Fonts:** Orbitron (headings), Share Tech Mono (body)
- **Colors:** Cyan (#29e6ff) primary, dark navy (#01060c) background, amber (#ffb347) warnings, red (#ff4d6d) danger, green (#3dffb5) success
- **Gold (#ffd700)** for Lawyer Mode accents
- **CSS:** ~135 lines of custom styles injected via `st.markdown`
- **Animations:** SVG spin (7s/14s/22s rings), pulse (2.4s), voice glow (2s)

---

## 6. Offline Mode

When no `ANTHROPIC_API_KEY` is set:
- All agents fall back to keyword-based processing
- Intake fills slots directly without LLM extraction
- Classifier uses keyword baseline only
- Demo findings with sample sources are displayed
- Full UI remains functional for design and demo purposes

---

## 7. Testing

- **Unit tests:** `tests/test_deadlines.py` (123 lines, 12 tests)
  - Deadline computation: today, 89 days, 91 days (expired), leap year, months, clamping
  - Date normalizer: today, yesterday, N days ago, explicit dates, unparseable
  - First steps knowledge base: load, find NYCT, missing entry
- Run with: `pytest tests/`

---

## 8. Dependencies

```
streamlit>=1.40
anthropic>=1.0
python-dotenv>=1.0
elevenlabs>=1.0
reportlab (pre-installed in conda env)
```

---

## 9. How to Run

```bash
# Option 1: Double-click launcher
open "/Users/jpromero/Ai-agent Legal Jarvis/launchers/JARVIS.command"

# Option 2: Manual
source /Users/jpromero/anaconda3/bin/activate && conda activate dev2
cd "/Users/jpromero/Ai-agent Legal Jarvis"
streamlit run app.py --server.port 8502
```

---

## 10. Known Limitations & Next Steps

### Current Limitations
- **CourtListener API** is keyed but not yet integrated into agent search pipeline
- **Open Legislation API** is keyed but not yet integrated
- **first_steps.json** has only 1 entry (NYCT torts) — needs expansion for all 12 law areas
- **Voice STT** requires Chrome/Edge/Safari (Web Speech API not supported in Firefox)
- **No user authentication** — single-user local app
- **No persistent chat history** across sessions (case.json saves facts but not full chat)

### Recommended Next Steps
1. **Wire CourtListener** into StatuteAgent for case law search
2. **Wire Open Legislation** into StatuteAgent for NY statute lookup
3. **Expand first_steps.json** with entries for all 12 law areas and common respondents
4. **Legal procedure workflow visualization** — flowchart showing the user's legal process steps
5. **Multi-case management** — list/resume prior cases from `cases/` directory
6. **RAG pipeline** — index legal documents for retrieval-augmented generation
7. **Authentication** if deployed publicly
8. **GitHub Actions** for automated testing

---

## 11. File-by-File Summary

| File | Lines | Purpose |
|------|-------|---------|
| `app.py` | 1,006 | Main Streamlit app: dashboard, voice overlay, lawyer mode UI, all rendering |
| `core/orchestrator.py` | 261 | 5-agent system, Claude API calls, web search, research pipeline |
| `core/lawyer.py` | 259 | Claude Legal chat, IRAC memo generation, PDF export via ReportLab |
| `core/intake.py` | 203 | CaseFile dataclass, question queue, date normalizer, MTA resolver, case folders |
| `core/voice.py` | 171 | ElevenLabs TTS, Web Speech API STT, multi-language support |
| `core/authority.py` | 117 | 5-tier source ranking, confidence scoring, domain classification |
| `core/classifier.py` | 96 | 12 law areas, keyword baseline, LLM classification |
| `core/deadlines.py` | 83 | Deadline computation (days/months), first_steps.json loader |
| `tests/test_deadlines.py` | 123 | 12 unit tests for deadlines, dates, and knowledge base |

**Total:** 2,319 lines of source code (including tests)

---

*Report generated by Claude Code for JARVIS Legal OS v0.1*
