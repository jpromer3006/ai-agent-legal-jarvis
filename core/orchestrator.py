"""Jarvis orchestrator: routes work to specialist agents and keeps an activity log.

Agents
  IntakeAgent      pulls facts and timeline events out of each answer
  ClassifierAgent  names the area(s) of law, with reasoning
  StatuteAgent     searches primary law only (.gov, courts, code libraries)
  ContextAgent     searches news, guides, video and community for context
  ValidatorAgent   checks every finding against source tiers, flags weak ones

Guardrail: Jarvis gives legal INFORMATION, never legal ADVICE. It never tells
a person what they should do in their specific case, never predicts outcomes,
and always points to licensed help for decisions.

With no ANTHROPIC_API_KEY set, every agent falls back to an offline mode so
the interface stays fully usable for design and demo work.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from .authority import Source, confidence, rank
from .classifier import AreaScore, LAW_AREAS, baseline_classify
from .intake import CaseFile

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

MODEL = os.getenv("JARVIS_MODEL", "claude-sonnet-5-5")

GUARDRAIL = """You are JARVIS, a legal information assistant. Hard rules:
1. Provide legal information only, never legal advice. Do not tell the person what they
   should do in their specific matter, do not predict outcomes, do not evaluate the
   strength of their case.
2. Ground every legal statement in a source. Prefer, in order: federal, state, and
   municipal government sites (.gov), courts, official code libraries; then Cornell LII,
   Justia, CourtListener, bar associations, legal aid; news only for current events;
   YouTube, Reddit, and social posts only as context, never as authority.
3. When a deadline might exist, say so plainly and tell the person to confirm it with a
   licensed attorney or legal aid organization right away.
4. If you are unsure or sources conflict, say that.
"""

STATUTE_DOMAINS = [
    "nysenate.gov", "legislation.nysenate.gov", "nycourts.gov", "nyc.gov", "ny.gov",
    "wcb.ny.gov", "codelibrary.amlegal.com", "congress.gov", "govinfo.gov", "ecfr.gov",
    "uscis.gov", "justice.gov", "dol.gov", "uscourts.gov", "supremecourt.gov",
    "law.cornell.edu", "law.justia.com", "courtlistener.com",
]


@dataclass
class Finding:
    title: str
    body: str
    agent: str
    sources: list[Source] = field(default_factory=list)
    status: str = "pending"   # verified | partial | unsupported

    @property
    def score(self) -> float:
        return confidence(self.sources)


@dataclass
class LogEntry:
    t: str
    agent: str
    msg: str


class Orchestrator:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=key) if (key and anthropic) else None
        self.log: list[LogEntry] = []
        self.findings: list[Finding] = []

    # ------------------------------------------------------------------ utils
    @property
    def online(self) -> bool:
        return self.client is not None

    def _log(self, agent: str, msg: str) -> None:
        self.log.append(LogEntry(time.strftime("%H:%M:%S"), agent, msg))

    def _ask_json(self, system: str, prompt: str, max_tokens: int = 1200) -> dict:
        resp = self.client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {}

    def _search(self, agent: str, prompt: str, allowed: list[str] | None, uses: int) -> Finding:
        tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": uses}
        if allowed:
            tool["allowed_domains"] = allowed
        resp = self.client.messages.create(
            model=MODEL, max_tokens=2500, system=GUARDRAIL,
            messages=[{"role": "user", "content": prompt}], tools=[tool],
        )
        body, sources = [], []
        for b in resp.content:
            if b.type == "text":
                body.append(b.text)
                for c in (getattr(b, "citations", None) or []):
                    sources.append(Source(c.url, c.title or "", getattr(c, "cited_text", "") or "", agent))
            elif b.type == "web_search_tool_result" and isinstance(b.content, list):
                for r in b.content:
                    sources.append(Source(r.url, r.title or "", "", agent))
        return Finding(title="", body="".join(body).strip(), agent=agent, sources=rank(sources))

    # ------------------------------------------------------------ IntakeAgent
    def extract_facts(self, case: CaseFile, answer: str) -> None:
        slot = case.pending_slot or "narrative"
        case.transcript.append({"role": "user", "text": answer})
        if not self.online:
            case.facts[slot] = answer
            self._log("IntakeAgent", f"filled {slot} (offline)")
            facts = {slot: answer}
        else:
            slots = [s for s, _ in case.question_queue()]
            data = self._ask_json(
                "You extract facts from a legal intake answer. Return only JSON.",
                f"Known facts: {json.dumps(case.facts)}\nSlots: {slots}\n"
                f"The person was asked about '{slot}'. Their answer: {answer!r}\n"
                'Return {"facts": {slot: short factual summary}, "timeline": [{"date": "...", "event": "..."}]}. '
                "Only include slots the answer actually addresses. Use the person's words, no guessing.",
            )
            facts = data.get("facts") or {slot: answer}
            case.facts.update({k: v for k, v in facts.items() if v})
            case.facts.setdefault(slot, answer)
            case.timeline.extend(data.get("timeline", []))

        # Post-extraction: normalize date and resolve entity
        from .intake import normalize_date, resolve_mta_entity
        if "when" in case.facts and case.when_iso is None:
            iso, raw = normalize_date(case.facts["when"])
            case.when_iso = iso
            case.when_raw = raw
            if iso:
                case.facts["when"] = f"{iso} ({raw})"
                self._log("IntakeAgent", f"date normalized: {iso}")
        if "public_entity" in case.facts and not case.resolved_entity:
            combined = " ".join([case.facts.get("narrative", ""),
                                 case.facts.get("where", ""),
                                 case.facts.get("public_entity", "")])
            resolved = resolve_mta_entity(combined)
            if resolved:
                case.resolved_entity = resolved
                self._log("IntakeAgent", f"entity resolved: {resolved}")
        self._log("IntakeAgent", f"filled {', '.join(facts)}")

    # ------------------------------------------------------- ClassifierAgent
    def classify(self, case: CaseFile) -> None:
        text = " ".join(case.facts.values())
        base = baseline_classify(text)
        if not self.online:
            case.areas = base
            self._log("ClassifierAgent", "keyword baseline: " + (", ".join(a.area for a in base) or "no signal yet"))
            return
        data = self._ask_json(
            GUARDRAIL + "\nReturn only JSON.",
            f"Account of events:\n{case.summary_text()}\n\nAreas: {list(LAW_AREAS)}\n"
            'Return {"areas": [{"area": name from list, "score": 0..1, "why": one sentence}]} '
            "ranked, max 3. Multiple areas can apply.",
        )
        areas = []
        for a in data.get("areas", []):
            if a.get("area") in LAW_AREAS:
                s = AreaScore(a["area"], float(a.get("score", 0)), [])
                s.why = a.get("why", "")
                areas.append(s)
        case.areas = areas or base
        self._log("ClassifierAgent", "areas: " + ", ".join(f"{a.area} {a.score:.0%}" for a in case.areas))

    # ---------------------------------------------------------- research run
    def research(self, case: CaseFile, jurisdiction: str = "New York, NY") -> list[Finding]:
        self.findings = []
        area = case.primary_area or "General"
        if not self.online:
            self.findings = demo_findings(area)
            self._log("StatuteAgent", "offline demo findings loaded")
            self._log("ValidatorAgent", "validated demo set")
            return self.findings

        facts = case.summary_text()
        self._log("StatuteAgent", f"searching primary law for {area} in {jurisdiction}")
        statute = self._search(
            "StatuteAgent",
            f"Area: {area}. Jurisdiction: {jurisdiction}.\nFacts:\n{facts}\n\n"
            "Identify the statutes, regulations, municipal codes, and official procedures that "
            "govern a matter like this, including any filing or notice deadlines. Cite each one.",
            STATUTE_DOMAINS, 6,
        )
        statute.title = f"Governing law: {area}"
        self.findings.append(statute)

        self._log("ContextAgent", "searching guides, news, and community context")
        context = self._search(
            "ContextAgent",
            f"Area: {area}. Jurisdiction: {jurisdiction}.\nFacts:\n{facts}\n\n"
            "Find plain language guides from legal aid or bar associations, recent news, and "
            "reputable explainer videos about this kind of matter. Label which are which.",
            None, 4,
        )
        context.title = "Plain language context"
        self.findings.append(context)

        self._validate()
        return self.findings

    # -------------------------------------------------------- ValidatorAgent
    def _validate(self) -> None:
        for f in self.findings:
            tiers = {s.tier for s in f.sources}
            if 1 in tiers:
                f.status = "verified"
            elif 2 in tiers:
                f.status = "partial"
            else:
                f.status = "unsupported"
            self._log("ValidatorAgent", f"'{f.title}' {f.status.upper()} ({len(f.sources)} sources, conf {f.score:.0%})")


def demo_findings(area: str) -> list[Finding]:
    """Offline sample so the HUD renders without an API key. Clearly labeled."""
    s = lambda u, t, a: Source(u, t, "", a)
    return [
        Finding(
            title=f"[DEMO] Governing law: {area}",
            body=("Sample output. With an API key set, the StatuteAgent searches only government, "
                  "court, and official code sources and cites each statute it names. Claims against "
                  "public entities in New York generally require a notice of claim within a short "
                  "statutory window, so confirm deadlines with a licensed attorney immediately."),
            agent="StatuteAgent", status="verified",
            sources=rank([
                s("https://www.nysenate.gov/legislation/laws/GMU/50-E", "NY General Municipal Law 50-E", "StatuteAgent"),
                s("https://www.nycourts.gov/courthelp/", "NY CourtHelp", "StatuteAgent"),
                s("https://www.law.cornell.edu/wex/negligence", "Negligence, Wex, Cornell LII", "StatuteAgent"),
            ]),
        ),
        Finding(
            title="[DEMO] Plain language context",
            body=("Sample output. The ContextAgent gathers legal aid guides, news, and videos. "
                  "Community sources appear here for context only and never count as authority."),
            agent="ContextAgent", status="partial",
            sources=rank([
                s("https://www.lawhelpny.org/", "LawHelpNY", "ContextAgent"),
                s("https://www.reuters.com/legal/", "Reuters Legal", "ContextAgent"),
                s("https://www.youtube.com/results?search_query=notice+of+claim+new+york", "YouTube explainers", "ContextAgent"),
                s("https://www.reddit.com/r/legaladvice/", "r/legaladvice", "ContextAgent"),
            ]),
        ),
    ]
