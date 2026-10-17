"""Source authority ranking.

Every source Jarvis touches gets a tier. Government and court sources are
primary law and always win. Commentary and social sources can add context
but can never be the sole support for a claim.

Special URL path rules:
  - nysenate.gov/legislation/bills/ → LEGISLATIVE HISTORY (not primary law)
  - mtaig.ny.gov → GOVERNMENT, NON-LEGAL (Inspector General, not law)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

# Tier 1: primary law. Federal, state, municipal government and courts.
# P1.2: .us removed — too broad (personal/commercial sites).
TIER1_SUFFIXES = (".gov", ".mil")
TIER1_DOMAINS = {
    "nycourts.gov", "nyc.gov", "ny.gov", "nysenate.gov", "uscourts.gov",
    "supremecourt.gov", "congress.gov", "govinfo.gov", "ecfr.gov",
    "federalregister.gov", "uscis.gov", "justice.gov", "dol.gov",
    "wcb.ny.gov", "codelibrary.amlegal.com", "legislation.nysenate.gov",
}

# Tier 2: trusted secondary legal sources.
TIER2_DOMAINS = {
    "law.cornell.edu", "justia.com", "law.justia.com", "courtlistener.com",
    "casetext.com", "findlaw.com", "nolo.com", "americanbar.org",
    "lexisnexis.com", "westlaw.com", "law.com", "scholar.google.com",
    "oyez.org", "lawhelpny.org", "lawhelp.org", "nycbar.org", "nysba.org",
    "legalaidnyc.org", "ilrc.org", "aila.org",
}

# Tier 3: reputable journalism.
TIER3_DOMAINS = {
    "reuters.com", "apnews.com", "nytimes.com", "wsj.com", "bloomberg.com",
    "bloomberglaw.com", "npr.org", "pbs.org", "propublica.org", "politico.com",
    "law360.com", "abajournal.com",
}

# Tier 4: community and video.
TIER4_DOMAINS = {
    "youtube.com", "youtu.be", "reddit.com", "x.com", "twitter.com",
    "tiktok.com", "quora.com", "facebook.com", "instagram.com", "medium.com",
}

# Government domains that are NOT primary law
GOV_NON_LEGAL_DOMAINS = {"mtaig.ny.gov"}

TIER_LABELS = {
    1: "PRIMARY LAW",
    2: "LEGAL SECONDARY",
    3: "NEWS",
    4: "COMMUNITY",
    5: "UNVERIFIED",
    6: "LEGISLATIVE HISTORY",
    7: "GOVERNMENT, NON-LEGAL",
}

TIER_WEIGHT = {
    1: 1.0, 2: 0.75, 3: 0.45, 4: 0.15, 5: 0.05,
    6: 0.3,  # legislative history (bills, not enacted law)
    7: 0.2,  # government non-legal (inspector general, etc.)
}


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
        self.tier = classify_url(self.url, self.domain)

    @property
    def label(self) -> str:
        return TIER_LABELS.get(self.tier, "UNVERIFIED")

    @property
    def weight(self) -> float:
        return TIER_WEIGHT.get(self.tier, 0.05)

    @property
    def can_support_claim_alone(self) -> bool:
        return self.tier <= 2


def domain_of(url: str) -> str:
    host = (urlparse(url).netloc or url).lower()
    return host[4:] if host.startswith("www.") else host


def _matches(domain: str, pool: set[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in pool)


def classify_url(url: str, domain: str | None = None) -> int:
    """Classify a URL into a tier, considering both domain and path."""
    if domain is None:
        domain = domain_of(url)
    path = urlparse(url).path.lower()

    # Special path rules (before domain rules)
    if "nysenate.gov" in domain and "/legislation/bills/" in path:
        return 6  # LEGISLATIVE HISTORY
    if _matches(domain, GOV_NON_LEGAL_DOMAINS):
        return 7  # GOVERNMENT, NON-LEGAL

    # Standard domain rules
    if _matches(domain, TIER1_DOMAINS) or domain.endswith(TIER1_SUFFIXES):
        return 1
    if _matches(domain, TIER2_DOMAINS):
        return 2
    if _matches(domain, TIER3_DOMAINS):
        return 3
    if _matches(domain, TIER4_DOMAINS):
        return 4
    return 5


# Backward compat alias
def classify_domain(domain: str) -> int:
    return classify_url("", domain)


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
