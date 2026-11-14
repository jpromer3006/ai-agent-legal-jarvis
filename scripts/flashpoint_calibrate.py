"""Flashpoint calibration: build the procedural survey and test it on
synthetic panels of each language community, BEFORE the demo.

For each test language (Spanish, Georgian, Egyptian Arabic):
  1. demographics      community language profile            ~$0.05
  2. tool_survey       build the 7 question survey + language ~$0.50
  3. panel             8 synthetic personas take it           ~$0.60
  4. panel status      poll until complete                    free
  5. tool_survey       analyze comprehension, suggest wording ~$0.50
Writes data/flashpoint_calibration.json, which the app loads to word every
question in the person's dialect. Total about $5 for all three languages.

Run from the project folder:
    python scripts/flashpoint_calibrate.py                 # all three
    python scripts/flashpoint_calibrate.py --lang Georgian
    python scripts/flashpoint_calibrate.py --dry-run       # print the plan, spend nothing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from core.flashpoint import FlashpointClient  # noqa: E402
from core.immigration import GAP_SURVEY, SURVEY  # noqa: E402
from core.languages import LANGUAGES, TEST_LANGUAGES  # noqa: E402

OUT = ROOT / "data" / "flashpoint_calibration.json"


def _find(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def survey_brief(language: str) -> str:
    qs = "\n".join(f"{i}. {s['q']}  Options: " + " | ".join(s["options"])
                   for i, s in enumerate(SURVEY[:-1], 1))
    gap = "\n".join(
        f"[{g['topic']}] SAY (agree 1-5): {g['say']} | BELIEVE (agree 1-5): {g['believe']} | "
        f"DO (Yes / No / Prefer not to say): {g['do']}" for g in GAP_SURVEY)
    return (
        f"Build and publish a survey titled 'Say, Believe, Do: immigration procedure, {language}'. "
        f"Audience: recent immigrants in New York City whose first language is {language}. "
        "Purpose: community research (never individual eligibility) on the gap between what "
        "people SAY in public, BELIEVE in private, and actually DO in immigration procedures, "
        "plus whether intake questions are understood.\n"
        "Block A, Say / Believe / Do (keep the three items of each topic together, randomize topic order):\n"
        + gap + "\n"
        "Block B, comprehension of these intake questions (single choice, exactly as written), each "
        "followed by an open end 'In your own words, what is this question asking?':\n" + qs + "\n"
        "End with: 'Which word or question was confusing, and how would people in your community say it?'. "
        f"Add {language} as a survey language and machine translate. No personal identifiers. "
        "Do not recruit paid respondents. Reply with the survey_id.")


def calibrate(fp: FlashpointClient, language: str, dry: bool) -> dict:
    comm = LANGUAGES[language]["community"]
    plan = {"language": language, "community": comm}
    if dry:
        plan["brief"] = survey_brief(language)
        return plan
    t0 = time.time()
    print(f"[{language}] demographics …", flush=True)
    demo = fp.demographics(comm["location"],
                           question=f"Share of residents born abroad and speaking {language} at home; "
                                    "English proficiency; education levels.",
                           audience=comm["label"])
    plan["demographics"] = demo.text[:3000]

    print(f"[{language}] building survey (60 to 600 s) …", flush=True)
    sv = fp.survey(survey_brief(language))
    survey_id = _find(r'"?survey_id"?\s*[:=]\s*"?([\w-]+)', sv.text)
    conv = _find(r'"?conversation_id"?\s*[:=]\s*"?([\w-]+)', sv.text)
    plan.update({"survey_id": survey_id, "conversation_id": conv, "survey_reply": sv.text[:2000]})
    if not survey_id:
        print(f"[{language}] no survey_id returned; see survey_reply", flush=True)
        return plan

    print(f"[{language}] synthetic panel create_and_run …", flush=True)
    pn = fp.synthetic_panel(
        name=f"JARVIS {language} immigrants NYC", n=8,
        objective=(f"Recent immigrants in New York City whose first language is {language}, "
                   "mixed ages and schooling, some with limited formal education, testing "
                   "whether immigration procedure questions are understood."),
        survey_id=survey_id, context=demo.text[:2500])
    job = _find(r'"?job_id"?\s*[:=]\s*"?([\w-]+)', pn.text)
    plan["panel_job"] = job
    deadline = time.time() + 25 * 60
    while job and time.time() < deadline:
        time.sleep(60)
        st = fp.panel_status(job)
        status = _find(r'"?status"?\s*[:=]\s*"?(\w+)', st.text) or "?"
        print(f"[{language}] panel {status}", flush=True)
        if status in ("completed", "failed", "interrupted"):
            plan["panel_status"] = status
            break

    print(f"[{language}] analyzing comprehension …", flush=True)
    an = fp.survey(
        "Analyze the synthetic panel responses. Part 1, GAP MAP: for each topic (court, "
        "address, notario, deadline, work) give the share who agree with SAY, the share who agree "
        "with BELIEVE, the share answering Yes to DO, and one sentence on the gap. Return Part 1 "
        "as JSON: {\"gap_map\": [{\"topic\":..., \"say_pct\":..., \"believe_pct\":..., "
        "\"do_pct\":..., \"gap\":...}]}. Part 2, COMPREHENSION: for each intake question, the "
        f"misunderstood words and a clearer everyday wording in {language} with an English gloss, "
        "then 5 wording rules for this community. Be concise.",
        conversation_id=conv, survey_id=survey_id)
    plan["notes"] = an.text[:4000]
    m = re.search(r'\{\s*"gap_map"\s*:\s*\[.*?\]\s*\}', an.text, re.S)
    if m:
        try:
            plan["gap_map"] = json.loads(m.group(0))["gap_map"]
        except json.JSONDecodeError:
            pass
    plan["minutes"] = round((time.time() - t0) / 60, 1)
    return plan


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=TEST_LANGUAGES)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--followup", action="store_true",
                    help="Build the 30 day DO follow up survey (one per language).")
    a = ap.parse_args()
    langs = [a.lang] if a.lang else TEST_LANGUAGES
    fp = FlashpointClient()
    if not fp.live and not a.dry_run:
        sys.exit("Add FLASHPOINT_API_KEY or FLASHPOINT_WALLET_PRIVATE_KEY to .env first.")
    if a.followup:
        for l in langs:
            r = fp.survey(
                f"Build a short 30 day follow up survey in English and {l} for people who used an "
                "immigration information intake. Ask only what they actually DID since: attended "
                "their hearing (Yes/No/No hearing yet), updated their address with the court or USCIS, "
                "filed any application, contacted free legal help, paid a notario. No names or case "
                "numbers. Do not distribute yet. Reply with the survey_id.")
            print(l, r.source, r.text[:600])
        return
    if fp.live and not a.dry_run:
        fp._ensure_session()          # open one session before the parallel runs
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for res in pool.map(lambda l: calibrate(fp, l, a.dry_run), langs):
            print(json.dumps(res, ensure_ascii=False, indent=2)[:1500])
            if not a.dry_run:
                data[res["language"]] = res
    if not a.dry_run:
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"saved {OUT}  ·  spent so far ${fp.spent_usdc():.2f}")


if __name__ == "__main__":
    main()
