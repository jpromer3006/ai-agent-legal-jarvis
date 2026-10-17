"""Source authority ranking.

Every source Jarvis touches gets a tier. Government and court sources are
primary law and always win. Commentary and social sources can add context
but can never be the sole support for a claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

# Tier 1: primary law. Federal, state, municipal government and courts.
TIER1_SUFFIXES = (".gov", ".mil", ".us")
TIER1_DOMAINS = {
    "nycourts.gov", "nyc.gov", "ny.gov", "nysenate.gov", "uscourts.gov",
    "supremecourt.gov", "congress.gov", "govinfo.gov", "ecfr.gov",
    "federalregister.gov", "uscis.gov", "justice.gov", "dol.gov",
    "wcb.ny.gov", "codelibrary.amlegal.com", "legislation.nysenate.gov",
}

# Tier 2: trusted secondary legal sources that reproduce or analyze primary law.
TIER2_DOMAINS = {
    "law.cornell.edu", "justia.com", "law.justia.com", "courtlistener.com",
    "casetext.com", "findlaw.com", "nolo.com", "americanbar.org",
    "lexisnexis.com", "westlaw.com", "law.com", "scholar.google.com",
    "oyez.org", "lawhelpny.org", "lawhelp.org", "nycbar.org", "nysba.org",
    "legalaidnyc.org", "ilrc.org", "aila.org",
}

# Tier 3: reputable journalism. Good for current events, not for law itself.
TIER3_DOMAINS = {
    "reuters.com", "apnews.com", "nytimes.com", "wsj.com", "bloomberg.com",
    "bloomberglaw.com", "npr.org", "pbs.org", "propublica.org", "politico.com",
    "law360.com", "abajournal.com",
}

# Tier 4: community and video. Context and lived experience only.
TIER4_DOMAINS = {
    "youtube.com", "youtu.be", "reddit.com", "x.com", "twitter.com",
    "tiktok.com", "quora.com", "facebook.com", "instagram.com", "medium.com",
}

TIER_LABELS = {
    1: "PRIMARY LAW",
    2: "LEGAL SECONDARY",
    3: "NEWS",
    4: "COMMUNITY",
    5: "UNVERIFIED",
}

TIER_WEIGHT = {1: 1.0, 2: 0.75, 3: 0.45, 4: 0.15, 5: 0.05}


@dataclass
class Source:
    url: str
    title: str = ""
    snippet: str = ""
    agent: str = ""
    tier: int = field(init=False)
    domain: str = field(init=False)

    def __post_init__(self) -> None:
        self.domain = domain_of(self.url)
        self.tier = classify_domain(self.domain)

    @property
    def label(self) -> str:
        return TIER_LABELS[self.tier]

    @property
    def weight(self) -> float:
        return TIER_WEIGHT[self.tier]

    @property
    def can_support_claim_alone(self) -> bool:
        return self.tier <= 2


def domain_of(url: str) -> str:
    host = (urlparse(url).netloc or url).lower()
    return host[4:] if host.startswith("www.") else host


def _matches(domain: str, pool: set[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in pool)


def classify_domain(domain: str) -> int:
    if _matches(domain, TIER1_DOMAINS) or domain.endswith(TIER1_SUFFIXES):
        return 1
    if _matches(domain, TIER2_DOMAINS):
        return 2
    if _matches(domain, TIER3_DOMAINS):
        return 3
    if _matches(domain, TIER4_DOMAINS):
        return 4
    return 5


def rank(sources: list[Source]) -> list[Source]:
    """Primary law first, then dedupe by URL."""
    seen, out = set(), []
    for s in sorted(sources, key=lambda s: s.tier):
        if s.url not in seen:
            seen.add(s.url)
            out.append(s)
    return out


def confidence(sources: list[Source]) -> float:
    """0..1 score: strongest source dominates, corroboration adds a little."""
    if not sources:
        return 0.0
    weights = sorted((s.weight for s in sources), reverse=True)
    score = weights[0] + 0.15 * sum(weights[1:4])
    return round(min(score, 1.0), 2)
