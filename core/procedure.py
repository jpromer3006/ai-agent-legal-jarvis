"""Legal procedure engine: select and locate stages in a legal process.

Pure functions, fully unit tested. Matches a case to the appropriate
procedure map and determines which stage the user is at based on their
case facts and done_signals.

All stage text uses "typically" or "commonly" — never "you will" or
"you should". This is an educational tool, not legal advice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "procedures.json"
_CACHE: dict | None = None


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        if _DATA.exists():
            _CACHE = json.loads(_DATA.read_text())
        else:
            _CACHE = {"procedures": []}
    return _CACHE


@dataclass
class StageStatus:
    """Status of a single stage in the procedure."""
    stage: dict
    status: str          # "done" | "current" | "upcoming" | "unknown"
    deadline_date: str | None = None
    days_remaining: int | None = None
    is_expired: bool = False
    rolled_from: str | None = None


@dataclass
class ProcedureResult:
    """A matched procedure with stage statuses."""
    procedure: dict
    stages: list[StageStatus]
    current_index: int = -1    # index of the current stage, or -1 if unknown


def select_procedure(area: str, respondent: str | None,
                     entity_confirmed: bool = False) -> dict | None:
    """Match a case to the best procedure based on area and respondent.

    Returns the procedure dict or None (which means use fallback).
    """
    data = _load()
    procedures = data.get("procedures", [])

    # Try specific match first
    for proc in procedures:
        applies = proc.get("applies_when", {})
        proc_area = applies.get("area", "")
        proc_types = applies.get("respondent_type", [])

        if proc_area == "_any":
            continue  # skip fallback in first pass

        if proc_area != area:
            continue

        # Check respondent type
        if "_private" in proc_types:
            # Private party — matches when no public entity or unconfirmed
            if not respondent or not entity_confirmed:
                return proc
        elif respondent and respondent in proc_types:
            return proc

    # Fallback
    for proc in procedures:
        if proc.get("applies_when", {}).get("area") == "_any":
            return proc

    return None


def locate_stages(case_facts: dict, case_actions: str,
                  procedure: dict,
                  deadline_data: dict | None = None) -> ProcedureResult:
    """Determine the status of each stage based on case facts.

    case_facts: the case.facts dict
    case_actions: combined text of actions_taken fact (for signal matching)
    procedure: the procedure dict from select_procedure
    deadline_data: optional dict of {deadline_ref: {date, days_remaining, expired}}

    Returns ProcedureResult with per-stage statuses.
    """
    stages = procedure.get("stages", [])
    results = []
    found_current = False
    all_facts_lower = {k: v.lower() for k, v in case_facts.items()}
    actions_lower = case_actions.lower()

    for stage in stages:
        signals = stage.get("done_signals", [])
        is_done = _check_signals(signals, all_facts_lower, actions_lower)

        # Attach deadline data if this stage has a deadline_ref
        dl_date = None
        dl_days = None
        dl_expired = False
        dl_rolled = None
        if stage.get("deadline_ref") and deadline_data:
            dl = deadline_data.get(stage["deadline_ref"], {})
            dl_date = dl.get("date")
            dl_days = dl.get("days_remaining")
            dl_expired = dl.get("expired", False)
            dl_rolled = dl.get("rolled_from")

        if is_done:
            status = "done"
        elif not found_current:
            status = "current"
            found_current = True
        else:
            status = "upcoming"

        results.append(StageStatus(
            stage=stage, status=status,
            deadline_date=dl_date, days_remaining=dl_days,
            is_expired=dl_expired, rolled_from=dl_rolled,
        ))

    # Find current index
    current_idx = next((i for i, s in enumerate(results) if s.status == "current"), -1)

    return ProcedureResult(
        procedure=procedure, stages=results, current_index=current_idx,
    )


def _check_signals(signals: list[str], facts: dict[str, str],
                   actions: str) -> bool:
    """Check if done_signals are satisfied by case facts.

    Signal formats:
      "narrative" — fact key exists
      "actions_taken:filed" — fact key contains the substring
    """
    if not signals:
        return False

    for sig in signals:
        if ":" in sig:
            key, val = sig.split(":", 1)
            fact_text = facts.get(key, "")
            if val.lower() in fact_text.lower():
                return True
            if val.lower() in actions:
                return True
        else:
            if sig in facts:
                return True
    return False
