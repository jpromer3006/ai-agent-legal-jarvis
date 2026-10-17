"""Deadline engine: compute filing deadlines from an incident date and a rule.

Pure functions, no side effects, no network calls.
"""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "first_steps.json"


@dataclass
class DeadlineResult:
    deadline_date: date
    days_remaining: int
    is_expired: bool
    label: str  # e.g., "90 days from incident"


def compute_deadline(incident_date: str | date, rule: dict,
                     today: date | None = None) -> DeadlineResult:
    """Compute a deadline from an incident date and a rule dict.

    rule: {"type": "days"|"months", "days_or_months": int, "trigger": "incident_date"}
    """
    if today is None:
        today = date.today()
    if isinstance(incident_date, str):
        incident = date.fromisoformat(incident_date)
    else:
        incident = incident_date

    n = rule["days_or_months"]
    kind = rule["type"]

    if kind == "days":
        deadline = incident + timedelta(days=n)
        label = f"{n} days from incident"
    elif kind == "months":
        # Add n months: same day, roll forward month
        m = incident.month + n
        y = incident.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        # Clamp day to last day of target month
        max_day = calendar.monthrange(y, m)[1]
        d = min(incident.day, max_day)
        deadline = date(y, m, d)
        label = f"{n} months from incident"
    else:
        raise ValueError(f"unknown deadline type: {kind}")

    remaining = (deadline - today).days
    return DeadlineResult(
        deadline_date=deadline,
        days_remaining=remaining,
        is_expired=remaining < 0,
        label=label,
    )


def load_first_steps() -> list[dict]:
    """Load the first_steps knowledge file."""
    if not _DATA.exists():
        return []
    return json.loads(_DATA.read_text())


def find_first_step(domain: str, respondent: str) -> dict | None:
    """Find the matching first step entry for an exact (domain, respondent) pair.

    No domain-only fallback — returns None when the respondent doesn't match.
    This prevents showing the wrong procedure (e.g., NYCT card for LIRR).
    """
    steps = load_first_steps()
    for s in steps:
        if s["domain"] == domain and s["respondent"] == respondent:
            return s
    return None
