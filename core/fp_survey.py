"""Flashpoint truth-seeking pre-survey for ViaNova Immigration.

Five empathy-first questions asked BEFORE the standard ViaNova intake.
Flashpoint scores each answer CLEAR / THIN / AVOIDED and returns a probe
list — attorney-ready follow-up questions for anything the person was
unwilling or unable to answer fully.

Privacy rule: only community-level descriptors (language + neighbourhood)
are sent to Flashpoint.AI.  No names, A-numbers, or personal story.
Offline fallback: if the Flashpoint call fails, local scoring is used.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("vianova.fp_survey")

# ---------------------------------------------------------------------------
# The 5 truth-seeking questions
# ---------------------------------------------------------------------------
FP_QUESTIONS: list[dict] = [
    {
        "id": "q1",
        "text_en": "Tell me in your own words what brought you here today — there are no wrong answers.",
        "signal": "urgency",
        "probe_en": "Can you tell me more about what's happening — what made today the day to reach out?",
    },
    {
        "id": "q2",
        "text_en": "Have you had any contact with immigration authorities — a court date, a letter, or a visit?",
        "signal": "court_exposure",
        "probe_en": "Sometimes people receive notices without fully understanding what they mean. Have you gotten any paperwork or letters recently, even ones you set aside?",
    },
    {
        "id": "q3",
        "text_en": "Is there anything that is hard to talk about — something that happened that you haven't told anyone yet?",
        "signal": "disclosure_barrier",
        "probe_en": "It is completely okay to share only what you are comfortable with. Even knowing there is something helps the attorney prepare. Can you say just a little about it?",
    },
    {
        "id": "q4",
        "text_en": "What is the one thing you most need help with right now?",
        "signal": "priority_need",
        "probe_en": "Sometimes the most urgent need is different from the reason a person first came in. What keeps you up at night about your situation?",
    },
    {
        "id": "q5",
        "text_en": "On a scale of 1 to 5, how safe do you feel answering these questions? 1 is not safe at all, 5 is completely safe.",
        "signal": "trust_level",
        "probe_en": "Thank you for being honest. What would need to change for you to feel safer sharing more with the attorney?",
    },
]

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
_SKIP_PHRASES = {
    "", "skip", "n/a", "na", "i don't know", "i dont know",
    "don't know", "dont know", "not sure", "nothing", "no", "none",
    "pass", "rather not say", "prefer not",
}

_THIN_WORD_MAX = 15
_VAGUE_SIGNAL_WORDS = {
    "stuff", "things", "something", "someone", "some", "maybe", "possibly",
    "might", "perhaps", "unclear", "complicated",
}


@dataclass
class FPResult:
    scores: dict[str, str]        # {"q1": "CLEAR"|"THIN"|"AVOIDED", ...}
    probe_list: list[str]         # human-phrased questions for the attorney
    summary: str                  # one-paragraph briefing (English)
    raw_fp_response: str = ""     # Flashpoint MCP response text, if any


# ---------------------------------------------------------------------------
# Local scoring (no LLM needed, works offline)
# ---------------------------------------------------------------------------
def score_fp_answers(answers: dict[str, str]) -> FPResult:
    """Score a dict {q_id: answer_text} → FPResult using heuristic rules.

    AVOIDED — empty / "skip" / very short / known evasion phrase
    THIN    — present but vague: 4-15 words with no specific nouns
    CLEAR   — specific, substantive answer
    """
    scores: dict[str, str] = {}
    probe_list: list[str] = []

    for q in FP_QUESTIONS:
        qid = q["id"]
        raw = str(answers.get(qid, "")).strip()
        lower = raw.lower()

        # AVOIDED
        if lower in _SKIP_PHRASES or len(lower) <= 3:
            scores[qid] = "AVOIDED"
            probe_list.append(q["probe_en"])
            continue

        words = re.findall(r"\b\w+\b", lower)
        word_count = len(words)

        # Check for specific nouns: dates, numbers, proper-ish nouns (len > 4, not vague)
        specific = any(
            (w[0].isupper() or re.match(r"\d", w) or (len(w) > 4 and w not in _VAGUE_SIGNAL_WORDS))
            for w in re.findall(r"\S+", raw)
        )

        vague_ratio = sum(1 for w in words if w in _VAGUE_SIGNAL_WORDS) / max(word_count, 1)

        if word_count <= _THIN_WORD_MAX and (not specific or vague_ratio > 0.3):
            scores[qid] = "THIN"
            probe_list.append(q["probe_en"])
        else:
            scores[qid] = "CLEAR"

    # Build summary paragraph
    avoided = [q["signal"] for q in FP_QUESTIONS if scores.get(q["id"]) == "AVOIDED"]
    thin = [q["signal"] for q in FP_QUESTIONS if scores.get(q["id"]) == "THIN"]
    clear_count = sum(1 for v in scores.values() if v == "CLEAR")

    summary_parts = [f"Pre-survey complete. {clear_count}/5 answers were clear."]
    if avoided:
        summary_parts.append(f"Topics not addressed: {', '.join(avoided)}.")
    if thin:
        summary_parts.append(f"Topics answered vaguely: {', '.join(thin)}.")
    if probe_list:
        summary_parts.append(
            "Attorney should probe: " + " | ".join(probe_list[:3])
            + ("..." if len(probe_list) > 3 else "")
        )

    return FPResult(
        scores=scores,
        probe_list=probe_list,
        summary=" ".join(summary_parts),
    )


# ---------------------------------------------------------------------------
# Flashpoint-enhanced scoring (MCP call)
# ---------------------------------------------------------------------------
def run_fp_survey(
    fp,                          # FlashpointClient instance
    answers: dict[str, str],
    language: str,
    community: str,
) -> FPResult:
    """Run the truth-seeking survey through Flashpoint, with offline fallback.

    fp        — FlashpointClient from core.flashpoint
    answers   — {q_id: answer_text} collected during the survey phase
    language  — user's language (English / Spanish / Georgian / Egyptian Arabic)
    community — community descriptor string from core.languages (no personal info)
    """
    # Offline / no-key fallback: use local scoring immediately
    if not fp.live:
        logger.info("fp_survey: Flashpoint offline, using local scoring")
        return score_fp_answers(answers)

    # Build an anonymised brief — no names, A-numbers, or personal story
    brief = (
        f"Community: {community}. Language: {language}. "
        f"Pre-intake survey answers (no personal identifiers): "
        + json.dumps({q["signal"]: answers.get(q["id"], "") for q in FP_QUESTIONS})
    )

    try:
        result = fp.survey(
            brief=brief,
            conversation_id="vianova_fp_intake",
            survey_id="truth_seeking_v1",
        )
        base = score_fp_answers(answers)

        if result.ok and result.text:
            # Merge any additional probes Flashpoint suggests into the probe list
            fp_text = result.text
            extra_probes: list[str] = []
            for line in fp_text.split("\n"):
                line = line.strip().lstrip("-•*0123456789. ")
                if len(line) > 20 and "?" in line and line not in base.probe_list:
                    extra_probes.append(line)
            merged_probes = base.probe_list + extra_probes[:3]
            return FPResult(
                scores=base.scores,
                probe_list=merged_probes,
                summary=base.summary,
                raw_fp_response=fp_text[:1000],
            )
        return base

    except Exception as exc:
        logger.warning("fp_survey: Flashpoint call failed (%s), using local scoring", exc)
        return score_fp_answers(answers)
