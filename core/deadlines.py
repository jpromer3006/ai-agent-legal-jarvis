"""Deadline engine: compute filing deadlines from an incident date and a rule.

Pure functions, no side effects, no network calls.
Supports weekend and holiday rollover per NY GCL §25-a [VERIFY].
"""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "first_steps.json"
_HOLIDAYS_FILE = Path(__file__).resolve().parent.parent / "data" / "ny_holidays.json"
_HOLIDAYS_CACHE: set[date] | None = None


def _load_holidays() -> set[date]:
    """Load NY holidays from data/ny_holidays.json into a set of dates."""
    global _HOLIDAYS_CACHE
    if _HOLIDAYS_CACHE is None:
        _HOLIDAYS_CACHE = set()
        if _HOLIDAYS_FILE.exists():
            data = json.loads(_HOLIDAYS_FILE.read_text())
            for year_dates in data.get("holidays", {}).values():
                for d in year_dates:
                    try:
                        _HOLIDAYS_CACHE.add(date.fromisoformat(d))
                    except ValueError:
                        pass
    return _HOLIDAYS_CACHE


def _rollover(d: date) -> tuple[date, date | None]:
    """Roll a date forward past weekends and holidays.

    Returns (rolled_date, original_date_if_rolled or None).
    Per NY GCL §25-a, when a deadline falls on Saturday, Sunday,
    or a public holiday, it typically extends to the next business day [VERIFY].
    """
    holidays = _load_holidays()
    original = d
    while d.weekday() >= 5 or d in holidays:  # 5=Saturday, 6=Sunday
        d += timedelta(days=1)
    return d, (original if d != original else None)


@dataclass
class DeadlineResult:
    deadline_date: date
    days_remaining: int
    is_expired: bool
    label: str
    rolled_from: date | None = None  # original date before rollover


def compute_deadline(incident_date: str | date, rule: dict,
                     today: date | None = None,
                     apply_rollover: bool = True) -> DeadlineResult:
    """Compute a deadline from an incident date and a rule dict.

    rule: {"type": "days"|"months", "days_or_months": int, "trigger": "incident_date"}
    apply_rollover: if True, roll weekends/holidays forward per GCL §25-a.
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
        m = incident.month + n
        y = incident.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        max_day = calendar.monthrange(y, m)[1]
        d = min(incident.day, max_day)
        deadline = date(y, m, d)
        label = f"{n} months from incident"
    else:
        raise ValueError(f"unknown deadline type: {kind}")

    rolled_from = None
    if apply_rollover:
        deadline, rolled_from = _rollover(deadline)

    remaining = (deadline - today).days
    return DeadlineResult(
        deadline_date=deadline,
        days_remaining=remaining,
        is_expired=remaining < 0,
        label=label,
        rolled_from=rolled_from,
    )


def load_first_steps() -> list[dict]:
    """Load the first_steps knowledge file."""
    if not _DATA.exists():
        return []
    return json.loads(_DATA.read_text())


def find_first_step(domain: str, respondent: str) -> dict | None:
    """Find the matching first step entry for an exact (domain, respondent) pair.

    No domain-only fallback — returns None when the respondent doesn't match.
    """
    steps = load_first_steps()
    for s in steps:
        if s["domain"] == domain and s["respondent"] == respondent:
            return s
    return None
