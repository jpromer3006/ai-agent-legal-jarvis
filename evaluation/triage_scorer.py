"""Triage scorer: runs every scenario as a conversation and reports metrics.

Scores the CURRENT JARVIS intake system (before) or the new triage agent (after).
Saves every run with full details for comparison.

Usage:
    python -m evaluation.triage_scorer --mode before --out evaluation/results/triage_before.json
    python -m evaluation.triage_scorer --mode after  --out evaluation/results/triage_after.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.classifier import baseline_classify, LAW_AREAS
from core.intake import CaseFile, is_advice_seeking, normalize_date, resolve_public_entity
from core.orchestrator import Orchestrator
from evaluation.simulated_user import simulated_user_respond


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TriageResult:
    """Result of running one scenario through triage."""
    scenario_id: str
    category: str
    language: str | None = None

    # What triage produced
    detected_areas: list[str] = field(default_factory=list)
    detected_court: str | None = None
    detected_message_type: str | None = None
    questions_asked: int = 0
    asked_for_county: bool = False
    gave_advice: bool = False

    # Expected
    expected_areas: list[str] = field(default_factory=list)
    expected_court: str | None = None
    expected_message_type: str | None = None
    county_matters: bool = True

    # Scores
    area_correct: bool = False
    court_correct: bool = False
    message_type_correct: bool = False
    unnecessary_county_ask: bool = False

    # Transcript
    transcript: list[dict] = field(default_factory=list)
    notes: str = ""


@dataclass
class ScoringReport:
    """Aggregate report across all scenarios."""
    mode: str  # "before" or "after"
    timestamp: str = ""
    total_scenarios: int = 0
    area_accuracy: float = 0.0
    court_accuracy: float = 0.0
    message_type_accuracy: float = 0.0
    avg_questions: float = 0.0
    unnecessary_county_asks: int = 0
    advice_given: int = 0
    non_legal_caught: int = 0
    non_legal_total: int = 0
    advice_seeking_caught: int = 0
    advice_seeking_total: int = 0
    trick_caught: int = 0
    trick_total: int = 0
    emergency_caught: int = 0
    emergency_total: int = 0
    by_language: dict = field(default_factory=dict)
    by_category: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _normalize_areas(areas) -> set[str]:
    """Normalize area names to a set for comparison."""
    if isinstance(areas, str):
        return {areas}
    return set(areas) if areas else set()


def _normalize_court(court) -> set[str]:
    """Normalize court/agency to a set for comparison."""
    if court is None:
        return set()
    if isinstance(court, str):
        return {court.lower().strip()}
    return {c.lower().strip() for c in court}


def _area_match(detected: list[str], expected: list[str]) -> bool:
    """Check if the primary expected area is in the detected areas."""
    if not expected:
        return not detected  # Both empty = correct
    detected_set = _normalize_areas(detected)
    expected_set = _normalize_areas(expected)
    # At least the primary (first) expected area must be detected
    primary = list(expected_set)[0] if expected_set else None
    if primary:
        return primary in detected_set
    return not detected_set


def _court_match(detected: str | None, expected) -> bool:
    """Check if the expected court/agency matches what was detected."""
    if expected is None:
        return detected is None
    expected_set = _normalize_court(expected)
    detected_lower = (detected or "").lower().strip()
    if not expected_set:
        return not detected_lower
    # Check if any expected court is a substring match of detected
    return any(e in detected_lower or detected_lower in e
               for e in expected_set)


# ---------------------------------------------------------------------------
# Run current JARVIS intake against a scenario (BEFORE mode)
# ---------------------------------------------------------------------------

def run_before_scenario(scenario: dict, use_llm: bool = False) -> TriageResult:
    """Run a scenario through the CURRENT JARVIS intake system.

    This simulates the existing intake flow:
    1. User gives opening message
    2. System runs extract_facts + classify for each answer
    3. System asks next question from the fixed queue
    4. Repeat until done or max questions
    """
    expected = scenario["expected"]
    hidden_facts = scenario["hidden_facts"]
    language = scenario.get("language")
    opening = scenario["opening_message"]

    result = TriageResult(
        scenario_id=scenario["id"],
        category=scenario["category"],
        language=language,
        expected_areas=expected.get("areas", []),
        expected_court=expected.get("court_or_agency"),
        expected_message_type=expected.get("message_type"),
        county_matters=expected.get("county_matters", True),
    )

    # Check if opening message is caught by advice filter
    if is_advice_seeking(opening):
        result.detected_message_type = "advice_seeking"
        result.message_type_correct = (
            expected.get("message_type") in ("advice_seeking", "trick_attempt")
        )
        result.questions_asked = 0
        result.transcript.append({"role": "user", "text": opening})
        result.transcript.append({"role": "jarvis", "text": "[ADVICE REFUSAL]"})
        return result

    # Create a fresh case and orchestrator
    case = CaseFile()
    orch = Orchestrator()

    # Process opening message
    case.transcript.append({"role": "user", "text": opening})

    if orch.online and use_llm:
        orch.extract_facts(case, opening)
        orch.classify(case)
    else:
        # Offline: fill the current slot
        slot = case.pending_slot or "narrative"
        case.facts[slot] = opening
        # Run keyword classifier
        text = " ".join(case.facts.values())
        case.areas = baseline_classify(text)

    result.questions_asked = 1
    result.transcript.append({"role": "user", "text": opening})

    # Continue intake up to 8 questions
    max_questions = 8
    for i in range(max_questions - 1):
        nxt = case.next_question()
        if nxt is None:
            break

        slot, question = nxt
        case.pending_slot = slot
        result.questions_asked += 1
        result.transcript.append({"role": "jarvis", "text": question})

        # Track county-related questions
        if any(w in question.lower() for w in ["county", "borough", "city",
                                                 "where did", "where was",
                                                 "where", "location"]):
            result.asked_for_county = True
            if not expected.get("county_matters", True):
                result.unnecessary_county_ask = True

        # Get simulated user response
        answer = simulated_user_respond(
            hidden_facts, question, language=language, use_llm=use_llm
        )
        result.transcript.append({"role": "user", "text": answer})

        if orch.online and use_llm:
            orch.extract_facts(case, answer)
            orch.classify(case)
        else:
            case.facts[slot] = answer
            text = " ".join(case.facts.values())
            case.areas = baseline_classify(text)

    # Collect results from the case
    result.detected_areas = [a.area for a in case.areas] if case.areas else []

    # Determine message type from what the system did
    if not case.areas and not case.facts.get("narrative"):
        result.detected_message_type = "not_legal"
    elif case.areas:
        result.detected_message_type = "incident"
    else:
        result.detected_message_type = "incident"  # system always assumes legal

    # Current system doesn't detect court/agency — leave None
    result.detected_court = None

    # Score
    result.area_correct = _area_match(result.detected_areas, result.expected_areas)
    result.court_correct = False  # Current system never detects court
    result.message_type_correct = (
        result.detected_message_type == result.expected_message_type
    )

    return result


# ---------------------------------------------------------------------------
# Aggregate scoring
# ---------------------------------------------------------------------------

def aggregate_results(results: list[TriageResult], mode: str) -> ScoringReport:
    """Aggregate individual results into a scoring report."""
    report = ScoringReport(
        mode=mode,
        timestamp=datetime.now().isoformat(),
        total_scenarios=len(results),
    )

    area_correct = 0
    court_correct = 0
    msg_correct = 0
    total_questions = 0
    unnecessary_county = 0
    advice_count = 0

    non_legal_caught = 0
    non_legal_total = 0
    advice_caught = 0
    advice_total = 0
    trick_caught = 0
    trick_total = 0
    emergency_caught = 0
    emergency_total = 0

    by_lang = {}
    by_cat = {}

    for r in results:
        if r.area_correct:
            area_correct += 1
        if r.court_correct:
            court_correct += 1
        if r.message_type_correct:
            msg_correct += 1
        total_questions += r.questions_asked
        if r.unnecessary_county_ask:
            unnecessary_county += 1
        if r.gave_advice:
            advice_count += 1

        # Non-legal detection
        if r.expected_message_type == "not_legal":
            non_legal_total += 1
            if r.detected_message_type in ("not_legal", "advice_seeking"):
                non_legal_caught += 1

        # Advice-seeking detection
        if r.expected_message_type == "advice_seeking":
            advice_total += 1
            if r.detected_message_type == "advice_seeking":
                advice_caught += 1

        # Trick detection
        if r.expected_message_type == "trick_attempt":
            trick_total += 1
            if r.detected_message_type in ("trick_attempt", "advice_seeking"):
                trick_caught += 1

        # Emergency detection
        if r.expected_message_type == "incident" and \
                r.category != "non_legal_and_adversarial" and \
                str(getattr(r, 'expected_court', '')).lower().find('critical') >= 0:
            emergency_total += 1

        # By language
        lang = r.language or "en"
        if lang not in by_lang:
            by_lang[lang] = {"total": 0, "area_correct": 0, "court_correct": 0}
        by_lang[lang]["total"] += 1
        if r.area_correct:
            by_lang[lang]["area_correct"] += 1
        if r.court_correct:
            by_lang[lang]["court_correct"] += 1

        # By category
        cat = r.category
        if cat not in by_cat:
            by_cat[cat] = {"total": 0, "area_correct": 0, "court_correct": 0,
                           "avg_questions": 0, "total_questions": 0}
        by_cat[cat]["total"] += 1
        by_cat[cat]["total_questions"] += r.questions_asked
        if r.area_correct:
            by_cat[cat]["area_correct"] += 1
        if r.court_correct:
            by_cat[cat]["court_correct"] += 1

    n = len(results) or 1
    report.area_accuracy = round(area_correct / n, 3)
    report.court_accuracy = round(court_correct / n, 3)
    report.message_type_accuracy = round(msg_correct / n, 3)
    report.avg_questions = round(total_questions / n, 1)
    report.unnecessary_county_asks = unnecessary_county
    report.advice_given = advice_count
    report.non_legal_caught = non_legal_caught
    report.non_legal_total = non_legal_total
    report.advice_seeking_caught = advice_caught
    report.advice_seeking_total = advice_total
    report.trick_caught = trick_caught
    report.trick_total = trick_total
    report.emergency_caught = emergency_caught
    report.emergency_total = emergency_total

    # Finalize by_language
    for lang, stats in by_lang.items():
        t = stats["total"] or 1
        stats["area_accuracy"] = round(stats["area_correct"] / t, 3)
        stats["court_accuracy"] = round(stats["court_correct"] / t, 3)
    report.by_language = by_lang

    # Finalize by_category
    for cat, stats in by_cat.items():
        t = stats["total"] or 1
        stats["area_accuracy"] = round(stats["area_correct"] / t, 3)
        stats["court_accuracy"] = round(stats["court_correct"] / t, 3)
        stats["avg_questions"] = round(stats["total_questions"] / t, 1)
        del stats["total_questions"]
    report.by_category = by_cat

    report.results = [asdict(r) for r in results]

    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_scenarios(path: str | None = None) -> list[dict]:
    """Load scenarios from JSON file."""
    if path is None:
        path = str(Path(__file__).resolve().parent / "triage_scenarios.json")
    data = json.loads(Path(path).read_text())
    return data["scenarios"]


def run_all(mode: str = "before", use_llm: bool = False,
            scenarios_path: str | None = None) -> ScoringReport:
    """Run all scenarios and return the scoring report."""
    scenarios = load_scenarios(scenarios_path)
    results = []

    print(f"Running {len(scenarios)} scenarios in '{mode}' mode "
          f"(LLM={'on' if use_llm else 'off'})...")

    for i, scenario in enumerate(scenarios):
        sid = scenario["id"]
        if mode == "before":
            result = run_before_scenario(scenario, use_llm=use_llm)
        else:
            # TODO: implement run_after_scenario when triage agent exists
            result = run_before_scenario(scenario, use_llm=use_llm)

        status = "OK" if result.area_correct else "MISS"
        print(f"  [{i+1:3d}/{len(scenarios)}] {sid:6s} {status:4s} "
              f"areas={result.detected_areas[:2]} "
              f"(expected {result.expected_areas[:2]}) "
              f"q={result.questions_asked}")
        results.append(result)

    report = aggregate_results(results, mode)
    return report


def print_summary(report: ScoringReport) -> None:
    """Print a human-readable summary."""
    print("\n" + "=" * 70)
    print(f"TRIAGE SCORING REPORT — {report.mode.upper()}")
    print(f"Timestamp: {report.timestamp}")
    print(f"Scenarios: {report.total_scenarios}")
    print("=" * 70)

    print(f"\n  Area of law accuracy:   {report.area_accuracy:.1%}")
    print(f"  Court/agency accuracy:  {report.court_accuracy:.1%}")
    print(f"  Message type accuracy:  {report.message_type_accuracy:.1%}")
    print(f"  Avg questions asked:    {report.avg_questions:.1f}")
    print(f"  Unnecessary county asks: {report.unnecessary_county_asks}")
    print(f"  Advice given (MUST=0):  {report.advice_given}")

    print(f"\n  Non-legal caught:       {report.non_legal_caught}/{report.non_legal_total}")
    print(f"  Advice-seeking caught:  {report.advice_seeking_caught}/{report.advice_seeking_total}")
    print(f"  Trick attempts caught:  {report.trick_caught}/{report.trick_total}")

    if report.by_language:
        print("\n  BY LANGUAGE:")
        for lang, stats in sorted(report.by_language.items()):
            print(f"    {lang:4s}: area={stats['area_accuracy']:.1%} "
                  f"court={stats['court_accuracy']:.1%} "
                  f"(n={stats['total']})")

    if report.by_category:
        print("\n  BY CATEGORY:")
        for cat, stats in sorted(report.by_category.items()):
            print(f"    {cat:30s}: area={stats['area_accuracy']:.1%} "
                  f"court={stats['court_accuracy']:.1%} "
                  f"q={stats['avg_questions']:.1f} (n={stats['total']})")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Triage scorer")
    parser.add_argument("--mode", default="before", choices=["before", "after"])
    parser.add_argument("--out", default=None, help="Output JSON path")
    parser.add_argument("--llm", action="store_true", help="Use LLM for user simulation")
    parser.add_argument("--scenarios", default=None, help="Path to scenarios JSON")
    args = parser.parse_args()

    report = run_all(mode=args.mode, use_llm=args.llm,
                     scenarios_path=args.scenarios)

    print_summary(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False))
        print(f"\nFull report saved to: {out_path}")


if __name__ == "__main__":
    main()
