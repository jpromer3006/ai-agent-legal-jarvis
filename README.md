# JARVIS Immigration

**Hack the Unreachable · Fordham · Nov 14, 2026**

> *People say one thing and do another.* JARVIS Immigration closes that gap for immigrants who are hardest to reach. It hears what a person **says** in their own language and dialect. It checks that against what they **believe and do**, using a private survey calibrated by Flashpoint.AI. Then it shows the procedure, the rules, the official forms, and the .gov tools for the status problems they actually face.

English is the main language. Spanish, Georgian, and Egyptian Arabic are the three test languages. JARVIS gives legal **information**, not legal advice.

## The problem: immigration status
* Complex, slow application processes with long processing backlogs
* Restricted work authorization
* Detention risk and fear of deportation
* Possible family separation

These hit hardest for asylum seekers and undocumented people, who often speak a language few courts have interpreters for.

## Workflow (shown live in the app's top tracker)

| # | Step | Who | What happens |
|---|------|-----|--------------|
| 1.1 | **Inquiry & Triage** | JARVIS AI + Flashpoint | Bilingual voice intake. ElevenLabs Scribe transcribes, Claude reads the dialect, and questions come back in the person's own variety. Then a **private 8 question check** runs, and the gap detector compares what was *said* with what was *tapped*. |
| 1.2 | **Conflict Check & Screening** | JARVIS screens · Staff clears | Other parties' names are checked against `data/firm_clients.json`. Names never leave the computer. |
| 1.3 | **Initial Consultation** | Attorney | Lawyer Mode: case summary, research chat, IRAC memo. The attorney sets the category (removal defense, humanitarian, family, employment…). |
| 1.4 | **Engagement** | Attorney + Client | JARVIS drafts an engagement summary; staff confirm the retainer and fee or fee waiver. |
| 2.1 | **Matter Creation** | JARVIS AI | Matter number such as `IMM-20261114-AR-COURT-XXXX`, opened automatically on engagement. |
| 2.2 | **Document Collection** | Client | A checklist built for the category and stage, translated into the client's language. Uploads go to the local matter folder only. |
| 2.3 | **Readiness Audit** | JARVIS pre audit · Paralegal confirms | Claude vision checks quality only (wrong document, illegible, expired, name spelling, missing translation) and sorts files into Ready / Red flags / Missing. |

## Where Flashpoint.AI is used (MCP + x402)

| When | Flashpoint tool | What it gives JARVIS |
|------|-----------------|----------------------|
| **Before** the demo, per language | `demographics` → `tool_survey` → `panel` (synthetic) → `tool_survey` analysis | **Say / Believe / Do gap map** for each community (court attendance, address updates, notarios, asylum deadline, work), plus comprehension notes that reword every question in that dialect |
| **During** intake | `demographics` (live, on the COMMUNITY LENS button) | The language and English proficiency profile of the person's neighborhood |
| **After** (30 days) | `tool_survey` (`--followup`) | What people actually **did**: attended, updated their address, filed, got legal help |

**Privacy:** Flashpoint only ever receives an anonymous community description, for example "Georgian speaking immigrants, South Brooklyn". It never receives a name, story, A-number, or status.

## Run it
```bash
conda activate dev2
pip install -r requirements.txt
streamlit run app.py          # or double click JARVIS_IMMIGRATION.command (port 8503)
```

### Keys (`.env`, never commit)
```
ANTHROPIC_API_KEY=...                 # your key (fallback)
ANTHROPIC_API_KEY_HACKATHON=...       # organizer key, used first today
ELEVENLABS_API_KEY=...                # voice in (Scribe) and voice out
FLASHPOINT_WALLET_PRIVATE_KEY=0x...   # funded Base wallet (x402)   OR
FLASHPOINT_API_KEY=...                # bearer token if a mentor issued one
```
Without a Flashpoint key the app still runs from cached or offline results. Each card shows **LIVE**, **CACHE** or **OFFLINE** so the demo stays honest.

### Flashpoint calibration (about 25 minutes, about $5 USDC for all three languages)
```bash
python scripts/flashpoint_calibrate.py --dry-run     # see the exact survey briefs, spends nothing
python scripts/flashpoint_calibrate.py               # Spanish, Georgian, Egyptian Arabic in parallel
python scripts/flashpoint_calibrate.py --followup    # build the 30 day "Do" follow up survey
```
This writes `data/flashpoint_calibration.json`. The app reads it for the gap map and the dialect wording.

## Verified protocol (tested live today)
`POST /auth/wallet/challenge` → EIP-191 sign → `POST /auth/wallet/token` (1 hour JWT) → MCP `initialize` (Mcp-Session-Id) → `tools/call` → `402` with x402 v2 terms (USDC on Base, eip155:8453) → the x402 client signs EIP-3009 and retries.

## Guardrails
* Information, never advice. No outcome predictions, no "do you qualify".
* Never asks for an A-number, SSN, or passport number. The document audit never repeats ID numbers.
* Dialect analysis is used only to understand the person, never to judge nationality, credibility, or status.
* Every rule is cited and rechecked against .gov sources during research. Research agents are limited to official domains (uscis.gov, justice.gov/eoir, ecfr.gov, ice.gov, state.gov, nyc.gov, ny.gov…).
* Humans sign off on conflicts, consultation, engagement, and document readiness.
