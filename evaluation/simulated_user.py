"""Simulated user for triage evaluation.

Answers triage questions using ONLY the hidden fact sheet. Gives vague
answers sometimes (like a real person). Never reveals the expected answer
directly. Uses Claude to generate realistic, imperfect answers.

Can also run in offline mode with simple rule-based answers.
"""
from __future__ import annotations

import os
import random

try:
    import anthropic
except ImportError:
    anthropic = None

FAST_MODEL = os.getenv("JARVIS_FAST_MODEL", "claude-haiku-4-5-20251001")

SIMULATED_USER_SYSTEM = """You are simulating a real person contacting a legal help system.
You have a hidden fact sheet with the true details of your situation.

RULES:
1. Answer ONLY using information from the fact sheet. Do not invent new facts.
2. Be natural and conversational, like a real person. Use casual language.
3. Sometimes be vague or imprecise — say "a few weeks ago" instead of the exact date,
   or "somewhere in Brooklyn" instead of the exact address. Do this about 30% of the time.
4. Never volunteer the area of law, the correct court, or legal terminology unless
   you would naturally know it (e.g., most people know "eviction" but not "holdover proceeding").
5. If asked something not in your fact sheet, say you don't know or aren't sure.
6. Show emotion where appropriate — frustration, fear, confusion.
7. Keep answers to 1-3 sentences unless the question calls for more detail.
8. If the fact sheet says you speak a non-English language, respond in that language."""


def build_user_prompt(fact_sheet: dict, question: str, language: str | None = None) -> str:
    """Build the prompt for the simulated user."""
    facts_text = "\n".join(f"- {k}: {v}" for k, v in fact_sheet.items() if v)
    lang_note = f"\nRespond in {language}." if language and language != "en" else ""
    return (
        f"HIDDEN FACT SHEET:\n{facts_text}\n\n"
        f"The triage system just asked you:\n\"{question}\"\n\n"
        f"Respond as the person described in the fact sheet would.{lang_note}"
    )


def simulated_user_respond(fact_sheet: dict, question: str,
                           language: str | None = None,
                           use_llm: bool = True) -> str:
    """Generate a simulated user response to a triage question.

    Args:
        fact_sheet: the hidden_facts dict from the scenario
        question: the triage system's question
        language: language code (e.g., "es", "zh", "hi") or None for English
        use_llm: if True, use Claude; if False, use rule-based fallback
    """
    if use_llm and anthropic and os.getenv("ANTHROPIC_API_KEY"):
        return _llm_respond(fact_sheet, question, language)
    return _rule_based_respond(fact_sheet, question)


def _llm_respond(fact_sheet: dict, question: str, language: str | None) -> str:
    """Use Claude to generate a realistic answer."""
    client = anthropic.Anthropic()
    prompt = build_user_prompt(fact_sheet, question, language)
    resp = client.messages.create(
        model=FAST_MODEL,
        max_tokens=300,
        system=SIMULATED_USER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _rule_based_respond(fact_sheet: dict, question: str) -> str:
    """Simple rule-based responses from the fact sheet (offline fallback)."""
    q = question.lower()

    # Map common question patterns to fact sheet keys
    mappings = [
        (["what happened", "tell me", "describe", "explain"], "what_happened"),
        (["where", "location", "address", "city", "state", "county", "borough"],
         "where"),
        (["when", "date", "how long ago", "time"], "when"),
        (["who", "person", "company", "employer", "landlord", "other party"],
         "who"),
        (["hurt", "injur", "harm", "damage"], "harm"),
        (["document", "paper", "record", "evidence", "report"], "documents"),
        (["done", "action", "taken", "report", "filed", "called"], "actions_taken"),
    ]

    for patterns, key in mappings:
        if any(p in q for p in patterns):
            value = fact_sheet.get(key)
            if value:
                # Sometimes be vague (30% of the time)
                if random.random() < 0.3 and key == "when":
                    return "I'm not exactly sure of the date... maybe a few weeks ago?"
                return value
            return "I'm not sure about that."

    # Default: give the narrative
    return fact_sheet.get("what_happened", "I'm not sure what to say.")
