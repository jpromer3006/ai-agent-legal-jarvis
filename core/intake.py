"""Intake engine: the question system that takes an account of events.

The case file is a set of slots. Jarvis always asks about the most important
empty slot. Once a law area is detected, area specific follow ups join the
queue. Offline, each answer fills the slot that was asked; with the LLM on,
one answer can fill several slots at once (see orchestrator.extract_facts).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

CORE_QUESTIONS: list[tuple[str, str]] = [
    ("narrative", "Tell me what happened, in your own words. Start wherever it makes sense to you."),
    ("when", "When did this happen? An exact date helps, because many claims have strict deadlines."),
    ("where", "Where did it happen? City, borough, and the specific place if you know it."),
    ("who", "Who else was involved? A person, a company, an agency, a landlord, an employer?"),
    ("harm", "What harm resulted? Injuries, money lost, property damaged, status affected?"),
    ("evidence", "What records do you have? Photos, reports, emails, medical papers, witnesses?"),
    ("actions_taken", "What have you already done about it? Reports filed, calls made, letters sent?"),
    ("goal", "What outcome are you hoping for?"),
]

AREA_QUESTIONS: dict[str, list[tuple[str, str]]] = {
    "Torts / Personal Injury": [
        ("public_entity", "Was a government agency or public authority involved, like the city, MTA, or NYCHA? Claims against them often have much shorter notice windows."),
        ("medical", "Did you get medical treatment? Where, and when was the first visit?"),
        ("report_number", "Was an incident or accident report made? Do you have a report number?"),
    ],
    "Workers Compensation": [
        ("employer_notice", "Did you tell your employer about the injury? When, and in writing or verbally?"),
        ("medical", "Have you seen a doctor about the injury, and did you say it was work related?"),
    ],
    "Immigration": [
        ("status", "What is your current immigration situation in general terms, and is there a deadline or notice date on any letter you received?"),
        ("notices", "Have you received any notices from USCIS or immigration court? What do they say at the top?"),
    ],
    "Criminal": [
        ("court_date", "Is there a court date? Which court?"),
        ("counsel", "Do you have a lawyer or public defender assigned yet?"),
    ],
    "Housing / Landlord Tenant": [
        ("lease", "Do you have a written lease? Is the unit rent stabilized, if you know?"),
        ("notices", "Have you received any court papers or notices from the landlord? What dates are on them?"),
    ],
    "Employment": [
        ("employer_size", "Roughly how many people work for the employer?"),
        ("documentation", "Do you have anything in writing, like texts, emails, pay stubs, or a termination letter?"),
    ],
}

SLOT_LABELS = {
    "narrative": "Account", "when": "Date", "where": "Location", "who": "Parties",
    "harm": "Harm", "evidence": "Evidence", "actions_taken": "Actions taken",
    "goal": "Goal", "public_entity": "Public entity", "medical": "Medical",
    "report_number": "Report #", "employer_notice": "Employer notice",
    "status": "Status", "notices": "Notices", "court_date": "Court date",
    "counsel": "Counsel", "lease": "Lease", "employer_size": "Employer size",
    "documentation": "Documentation",
}


# ---------------------------------------------------------------------------
# Date normalizer: relative text -> ISO 8601
# ---------------------------------------------------------------------------
_RELATIVE_PATTERNS = {
    r"\btoday\b": 0,
    r"\byesterday\b": -1,
    r"\b(\d+)\s+days?\s+ago\b": None,  # captured group
    r"\blast\s+week\b": -7,
    r"\blast\s+month\b": -30,
}


def normalize_date(raw: str, now: datetime | None = None) -> tuple[str | None, str]:
    """Return (iso_date or None, raw_text). Best effort, no guessing."""
    now = now or datetime.now()
    text = raw.strip().lower()

    # Try direct parse first (e.g., "October 14, 2026", "2026-10-14", "10/14/2026")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y",
                "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d"), raw
        except ValueError:
            continue

    # Relative patterns
    for pat, delta in _RELATIVE_PATTERNS.items():
        m = re.search(pat, text)
        if m:
            if delta is None:
                delta = -int(m.group(1))
            return (now + timedelta(days=delta)).strftime("%Y-%m-%d"), raw

    return None, raw


# ---------------------------------------------------------------------------
# MTA entity resolver
# ---------------------------------------------------------------------------
_MTA_ENTITIES: list[tuple[list[str], str]] = [
    (["subway", "train", "j train", "a train", "b train", "c train", "d train",
      "e train", "f train", "g train", "l train", "m train", "n train", "q train",
      "r train", "s train", "w train", "z train", "1 train", "2 train", "3 train",
      "4 train", "5 train", "6 train", "7 train",
      "station", "platform", "turnstile", "mta subway",
      "nyct bus", "city bus", "mta bus company"],
     "New York City Transit Authority"),
    (["lirr", "long island rail road", "long island railroad"],
     "Long Island Rail Road"),
    (["metro-north", "metro north", "metronorth", "mnr"],
     "Metro-North Commuter Railroad"),
    (["mta bus", "express bus"],
     "MTA Bus Company"),
    (["staten island railway", "sir ", "sir train"],
     "Staten Island Rapid Transit Operating Authority"),
]


def resolve_mta_entity(text: str) -> str | None:
    """Map free text to the correct MTA respondent, or None if no match."""
    low = " " + text.lower() + " "
    for keywords, entity in _MTA_ENTITIES:
        for kw in keywords:
            if kw in low:
                return entity
    if "mta" in low:
        return "New York City Transit Authority"
    return None


CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


@dataclass
class CaseFile:
    created: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    facts: dict[str, str] = field(default_factory=dict)
    areas: list = field(default_factory=list)          # list[AreaScore] or dicts from LLM
    timeline: list[dict] = field(default_factory=list)  # {"date","event"}
    transcript: list[dict] = field(default_factory=list)  # {"role","text"}
    pending_slot: str | None = None
    when_iso: str | None = None       # normalized ISO 8601 date
    when_raw: str | None = None       # original text the user typed
    resolved_entity: str | None = None
    entity_confirmed: bool = False
    folder: Path | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.folder is None:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.folder = CASES_DIR / f"case_{ts}"
        self.folder.mkdir(parents=True, exist_ok=True)

    @property
    def primary_area(self) -> str | None:
        if not self.areas:
            return None
        a = self.areas[0]
        return a.area if hasattr(a, "area") else a.get("area")

    def question_queue(self) -> list[tuple[str, str]]:
        queue = list(CORE_QUESTIONS)
        if self.primary_area in AREA_QUESTIONS:
            queue += AREA_QUESTIONS[self.primary_area]
        return queue

    def next_question(self) -> tuple[str, str] | None:
        for slot, q in self.question_queue():
            if slot not in self.facts:
                return slot, q
        return None

    def progress(self) -> float:
        queue = self.question_queue()
        done = sum(1 for slot, _ in queue if slot in self.facts)
        return done / len(queue) if queue else 0.0

    def summary_text(self) -> str:
        lines = [f"{SLOT_LABELS.get(k, k)}: {v}" for k, v in self.facts.items()]
        return "\n".join(lines)

    def save(self) -> Path:
        """Persist current case state to the case folder as JSON."""
        data = {
            "created": self.created,
            "facts": self.facts,
            "areas": [{"area": a.area, "score": a.score} if hasattr(a, "area") else a
                      for a in self.areas],
            "timeline": self.timeline,
            "transcript": self.transcript,
            "when_iso": self.when_iso,
            "resolved_entity": self.resolved_entity,
            "entity_confirmed": self.entity_confirmed,
        }
        out = self.folder / "case.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return out
