"""Intake engine: the question system that takes an account of events.

The case file is a set of slots. Jarvis always asks about the most important
empty slot. Once a law area is detected, area specific follow ups join the
queue. Offline, each answer fills the slot that was asked; with the LLM on,
one answer can fill several slots at once (see orchestrator.extract_facts).
"""
from __future__ import annotations

import json
import random
import re
import string
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
# Date normalizer: relative text -> ISO 8601 with confidence
# ---------------------------------------------------------------------------

@dataclass
class DateResult:
    """Result of date normalization with confidence level."""
    iso: str | None       # ISO date string or None
    raw: str              # original text
    confidence: str       # "exact" | "assumed" | "vague"


# Word numbers
_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
}

# Vague phrases that should NOT produce a date
_VAGUE_PHRASES = [
    r"\ba\s+while\s+ago\b", r"\bsome\s+time\s+ago\b", r"\brecently\b",
    r"\ba\s+few\s+(weeks?|months?)\s+ago\b",
]

# Exact relative patterns (produce a real date)
_EXACT_RELATIVE = [
    (r"\btoday\b", 0),
    (r"\bthe\s+day\s+before\s+yesterday\b", -2),
    (r"\byesterday\b", -1),
    (r"\b(\d+)\s+days?\s+ago\b", None),  # captured group
]


def normalize_date(raw: str, now: datetime | None = None) -> DateResult:
    """Normalize a date string. Returns DateResult with confidence level.

    confidence values:
      "exact"   — unambiguous date parsed or exact relative (yesterday, 3 days ago)
      "assumed" — year was assumed (e.g., "October 14" → current year)
      "vague"   — too vague to compute a date (last month, a while ago)
    """
    now = now or datetime.now()
    text = raw.strip().lower()

    # Check for vague phrases first — these should ask for clarification
    for pat in _VAGUE_PHRASES:
        if re.search(pat, text):
            return DateResult(iso=None, raw=raw, confidence="vague")

    # "last week" and "last month" are vague — no exact date
    if re.search(r"\blast\s+(week|month)\b", text):
        return DateResult(iso=None, raw=raw, confidence="vague")

    # Try direct parse with full year (exact)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y",
                "%B %d %Y", "%b %d %Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            # Reject future dates
            if parsed.date() > now.date():
                return DateResult(iso=None, raw=raw, confidence="vague")
            return DateResult(iso=parsed.strftime("%Y-%m-%d"), raw=raw,
                              confidence="exact")
        except ValueError:
            continue

    # Two-digit year formats — flag for confirmation
    for fmt in ("%m/%d/%y",):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.date() > now.date():
                return DateResult(iso=None, raw=raw, confidence="vague")
            return DateResult(iso=parsed.strftime("%Y-%m-%d"), raw=raw,
                              confidence="assumed")
        except ValueError:
            continue

    # Month + day without year (e.g., "October 14", "10/14") — assume current year
    for fmt in ("%B %d", "%b %d", "%m/%d"):
        try:
            parsed = datetime.strptime(text, fmt).replace(year=now.year)
            if parsed.date() > now.date():
                parsed = parsed.replace(year=now.year - 1)
            return DateResult(iso=parsed.strftime("%Y-%m-%d"), raw=raw,
                              confidence="assumed")
        except ValueError:
            continue

    # "Sept 30, 2026" variant
    for fmt in ("%b %d, %Y", "%b %d %Y"):
        try:
            parsed = datetime.strptime(text.replace("sept", "sep"), fmt)
            if parsed.date() > now.date():
                return DateResult(iso=None, raw=raw, confidence="vague")
            return DateResult(iso=parsed.strftime("%Y-%m-%d"), raw=raw,
                              confidence="exact")
        except ValueError:
            continue

    # Exact relative patterns
    for pat, delta in _EXACT_RELATIVE:
        m = re.search(pat, text)
        if m:
            if delta is None:
                delta = -int(m.group(1))
            iso = (now + timedelta(days=delta)).strftime("%Y-%m-%d")
            return DateResult(iso=iso, raw=raw, confidence="exact")

    # Word number days ago ("two days ago")
    m = re.search(r"\b(" + "|".join(_WORD_NUMS) + r")\s+days?\s+ago\b", text)
    if m:
        delta = -_WORD_NUMS[m.group(1)]
        iso = (now + timedelta(days=delta)).strftime("%Y-%m-%d")
        return DateResult(iso=iso, raw=raw, confidence="exact")

    return DateResult(iso=None, raw=raw, confidence="vague")


# ---------------------------------------------------------------------------
# Public entity resolver (data-driven, word-boundary regex)
# ---------------------------------------------------------------------------
_ENTITIES_FILE = Path(__file__).resolve().parent.parent / "data" / "public_entities.json"
_ENTITY_CACHE: dict | None = None


def _load_entity_rules() -> dict:
    global _ENTITY_CACHE
    if _ENTITY_CACHE is None:
        if _ENTITIES_FILE.exists():
            _ENTITY_CACHE = json.loads(_ENTITIES_FILE.read_text())
        else:
            _ENTITY_CACHE = {"non_mta_guards": [], "entities": []}
    return _ENTITY_CACHE


def resolve_public_entity(text: str) -> str | None:
    """Map free text to a public entity respondent, or None if uncertain.

    Uses word-boundary regex rules from data/public_entities.json.
    Most specific entities are checked first (LIRR before NYCT).
    Non-MTA guards prevent false positives (Amtrak, gas station, etc.).
    """
    rules = _load_entity_rules()
    low = text.lower()

    # Check non-MTA guards first — if any match, return None
    for guard in rules.get("non_mta_guards", []):
        if re.search(r"\b" + re.escape(guard) + r"\b", low):
            return None

    # Check entities in order (most specific first)
    for entity in rules.get("entities", []):
        for pattern in entity["patterns"]:
            if re.search(pattern, low):
                return entity["name"]

    return None


# Keep backward compat alias
def resolve_mta_entity(text: str) -> str | None:
    """Deprecated: use resolve_public_entity instead."""
    return resolve_public_entity(text)


def list_known_entities() -> list[str]:
    """Return list of known public entity names for the UI picker."""
    rules = _load_entity_rules()
    return [e["name"] for e in rules.get("entities", [])]


# ---------------------------------------------------------------------------
# Intent detection: filter advice-seeking questions
# ---------------------------------------------------------------------------
_ADVICE_PATTERNS = [
    r"\bshould i\b", r"\bwill i win\b", r"\bhow much.*(worth|get|money)\b",
    r"\bdo i need a lawyer\b", r"\bwrite my\b", r"\bfile.*for me\b",
    r"\bwhat should i do\b",
]


def is_advice_seeking(text: str) -> bool:
    """Return True if the text looks like an advice-seeking question."""
    low = text.strip().lower()
    for pat in _ADVICE_PATTERNS:
        if re.search(pat, low):
            return True
    # Pure question with no factual content
    if low.endswith("?") and len(low.split()) < 12:
        words = low.split()
        question_starters = {"should", "will", "can", "do", "how", "is", "would"}
        if words and words[0] in question_starters:
            return True
    return False


ADVICE_REFUSAL = (
    "I provide legal information, not legal advice. I can't tell you what to "
    "do, predict outcomes, or evaluate your case. For personalized guidance, "
    "contact a licensed attorney or a free legal aid organization like "
    "LawHelpNY (lawhelpny.org) or the NYC Bar Legal Referral Service."
)

# ---------------------------------------------------------------------------
# Case file
# ---------------------------------------------------------------------------
CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


def _random_suffix(n: int = 4) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


@dataclass
class CaseFile:
    created: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    facts: dict[str, str] = field(default_factory=dict)
    areas: list = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    pending_slot: str | None = None
    when_iso: str | None = None
    when_raw: str | None = None
    resolved_entity: str | None = None
    entity_confirmed: bool = False
    entity_rejected: bool = False
    folder: Path | None = field(default=None, repr=False)

    def __post_init__(self):
        # Folder path is computed but NOT created until save()
        if self.folder is None:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.folder = CASES_DIR / f"case_{ts}_{_random_suffix()}"

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
        """Persist current case state to the case folder as JSON.

        Creates the folder lazily on first call.
        """
        self.folder.mkdir(parents=True, exist_ok=True)
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
