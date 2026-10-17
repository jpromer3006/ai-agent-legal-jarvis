"""Law area classifier.

Two layers: a fast keyword baseline that always works offline, and an LLM
layer (in orchestrator.py) that refines it. The baseline also acts as a
sanity check on the LLM: if they disagree wildly, the UI shows both.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LAW_AREAS: dict[str, dict] = {
    "Torts / Personal Injury": {
        "icon": "TRT",
        "keywords": ["slip", "fell", "fall", "injur", "accident", "hurt", "negligen",
                     "bus", "subway", "train", "car crash", "collision", "hit by",
                     "dog bite", "malpractice", "wrongful death", "pothole", "sidewalk"],
    },
    "Workers Compensation": {
        "icon": "WCB",
        "keywords": ["at work", "on the job", "employer", "workplace injur", "workers comp",
                     "while working", "lost wages", "shift"],
    },
    "Immigration": {
        "icon": "IMM",
        "keywords": ["visa", "green card", "asylum", "deport", "uscis", "citizenship",
                     "naturaliz", "ice ", "removal", "daca", "work permit", "border"],
    },
    "Criminal": {
        "icon": "CRM",
        "keywords": ["arrest", "charged", "police", "jail", "bail", "misdemeanor",
                     "felony", "warrant", "summons", "prosecutor", "probation"],
    },
    "Housing / Landlord Tenant": {
        "icon": "HSG",
        "keywords": ["landlord", "tenant", "evict", "rent", "lease", "apartment",
                     "repairs", "mold", "heat", "nycha", "security deposit"],
    },
    "Employment": {
        "icon": "EMP",
        "keywords": ["fired", "terminated", "discriminat", "harass", "overtime",
                     "wage theft", "unpaid", "retaliat", "boss", "hostile"],
    },
    "Family": {
        "icon": "FAM",
        "keywords": ["divorce", "custody", "child support", "visitation", "alimony",
                     "order of protection", "adoption", "paternity"],
    },
    "Consumer / Debt": {
        "icon": "CON",
        "keywords": ["debt", "collector", "credit report", "scam", "refund",
                     "warranty", "repossess", "billing"],
    },
    "Contracts / Business": {
        "icon": "CTR",
        "keywords": ["contract", "breach", "agreement", "invoice", "vendor",
                     "llc", "partner", "nda"],
    },
    "Civil Rights": {
        "icon": "CVR",
        "keywords": ["excessive force", "civil rights", "first amendment",
                     "false arrest", "ada ", "disability access", "profil"],
    },
    "Estates / Probate": {
        "icon": "EST",
        "keywords": ["last will", "will and testament", "estate", "probate",
                     "inherit", "executor", "passed away"],
    },
    "Traffic / Vehicle": {
        "icon": "TRF",
        "keywords": ["ticket", "license suspended", "dmv", "speeding", "parking"],
    },
}


@dataclass
class AreaScore:
    area: str
    score: float
    hits: list[str]

    @property
    def icon(self) -> str:
        return LAW_AREAS[self.area]["icon"]


def baseline_classify(text: str, top_k: int = 3) -> list[AreaScore]:
    """Classify text using word-boundary keyword matching.

    P1.3: Uses \\b word boundaries instead of substring matching to avoid
    false positives like "bus" in "business" or "train" in "restraining".
    Multi-word phrases use their natural boundaries.
    """
    t = re.sub(r"\s+", " ", text.lower())
    scored = []
    for area, spec in LAW_AREAS.items():
        hits = []
        for kw in spec["keywords"]:
            # Multi-word phrases: match as-is with word boundaries
            # Single words: strict word boundary
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, t):
                hits.append(kw)
        if hits:
            scored.append(AreaScore(area, float(len(hits)), hits))
    total = sum(s.score for s in scored) or 1.0
    for s in scored:
        s.score = round(s.score / total, 2)
    return sorted(scored, key=lambda s: s.score, reverse=True)[:top_k]
