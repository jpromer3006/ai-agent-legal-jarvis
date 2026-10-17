# JARVIS Legal OS · Phase 1

A holographic command center that takes an account of events through guided questions, names the areas of law that may apply, and dispatches agents that research and cite official sources. Legal information only, never legal advice.

## Start it

**Mac, one time:** open Terminal in this folder and run

    bash launchers/make_mac_app.sh

A JARVIS icon appears on your Desktop. Click it from then on. The first launch builds its own Python environment (about a minute), then opens full screen in Chrome app mode.

**Windows:** double click `launchers/JARVIS.bat`. Make a desktop shortcut to it and set the icon to `assets/jarvis_icon.ico`.

**Manual:** `pip install -r requirements.txt` then `streamlit run app.py`

## Turn on live research

Copy `.env.example` to `.env` and add your Anthropic API key. Without a key, JARVIS runs in OFFLINE DEMO mode: the full interface works, classification uses the keyword baseline, and research shows labeled sample findings.

## How it is built

    app.py                 HUD interface (Streamlit + custom CSS + animated SVG reactor)
    core/intake.py         question engine and case file; core questions plus area follow ups
    core/classifier.py     law area taxonomy and offline keyword baseline
    core/authority.py      source tiers and confidence scoring
    core/orchestrator.py   the agents and the legal information guardrail
    core/voice.py          voice slot, phase 4 (listen and speak hooks already wired)

**Agents:** IntakeAgent extracts facts and timeline events from each answer. ClassifierAgent ranks up to three areas of law with reasoning. StatuteAgent searches only government, court, and official code domains. ContextAgent gathers legal aid guides, news, and video. ValidatorAgent marks each finding VERIFIED (has primary law), PARTIAL (secondary only), or UNSUPPORTED.

**Source tiers:** T1 primary law (.gov, courts, code libraries) · T2 legal secondary (Cornell LII, Justia, CourtListener, bar associations, legal aid, Lexis) · T3 news (Reuters, AP) · T4 community (YouTube, Reddit, X), context only and never authority · T5 unverified.

## Roadmap

1. **Phase 1 (this build):** HUD, intake, classification, cited research, validation.
2. **Phase 2:** vision intake (photograph a document or scene, get structured facts), case export as a PDF packet, saved cases.
3. **Phase 3:** more specialist agents (court calendar, agency forms, deadline calculator with sources), jurisdiction picker beyond NYC.
4. **Phase 4:** voice. Wake word "Jarvis", local Whisper speech to text, ElevenLabs speech out, voice commands for every button so no typing is needed.
