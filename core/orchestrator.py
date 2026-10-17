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
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from .authority import Source, confidence, rank
from .classifier import AreaScore, LAW_AREAS, baseline_classify
from .intake import CaseFile

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

logger = logging.getLogger("jarvis")

MODEL = os.getenv("JARVIS_MODEL", "claude-sonnet-5-5")
FAST_MODEL = os.getenv("JARVIS_FAST_MODEL", "claude-haiku-4-5-20251001")
# Note: check `anthropic model list` for current IDs. As of Oct 2026,
# claude-haiku-4-5-20251001 is the latest Haiku.

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

T = TypeVar("T")


def safe_call(fn: Callable[..., T], *args: Any, default: T = None,
              retries: int = 1, **kwargs: Any) -> T:
    """Call fn with retry and error handling. Never raises, never prints tracebacks.

    Args:
        fn: callable to invoke
        default: value to return on failure
        retries: number of retries after first failure (default 1)
    Returns:
        fn result on success, default on failure
    """
    for attempt in range(1 + retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.warning("safe_call attempt %d/%d failed: %s", attempt + 1, 1 + retries, e)
            if attempt == retries:
                return default
    return default


# -- Tool schemas for structured output -----------------------------------

EXTRACT_FACTS_TOOL = {
    "name": "extract_facts",
    "description": "Extract facts and timeline from a legal intake answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "object",
                "description": "Map of slot name to short factual summary extracted from the answer.",
                "additionalProperties": {"type": "string"},
            },
            "timeline": {
                "type": "array",
                "description": "Timeline events extracted from the answer.",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "event": {"type": "string"},
                    },
                    "required": ["date", "event"],
                },
            },
        },
        "required": ["facts", "timeline"],
    },
}

CLASSIFY_TOOL = {
    "name": "classify_areas",
    "description": "Classify the legal areas that apply to this account.",
    "input_schema": {
        "type": "object",
        "properties": {
            "areas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "area": {"type": "string", "description": "Name from the provided list"},
                        "score": {"type": "number", "description": "0 to 1 confidence"},
                        "why": {"type": "string", "description": "One sentence reason. No citations."},
                    },
                    "required": ["area", "score", "why"],
                },
                "maxItems": 3,
            },
        },
        "required": ["areas"],
    },
}


@dataclass
class Finding:
    title: str
    body: str
    agent: str
    sources: list[Source] = field(default_factory=list)
    consulted: list[Source] = field(default_factory=list)
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

    def _ask_structured(self, system: str, prompt: str, tool: dict,
                        model: str | None = None) -> dict:
        """Call Claude with forced tool use and return the tool input as a dict.

        Falls back to empty dict on any failure — never crashes.
        Uses prompt caching on the system prompt for speed.
        """
        def _call():
            # Use cache_control on system prompt for repeated calls
            sys_msg = [{"type": "text", "text": system,
                        "cache_control": {"type": "ephemeral"}}]
            resp = self.client.messages.create(
                model=model or FAST_MODEL,
                max_tokens=1200,
                system=sys_msg,
                messages=[{"role": "user", "content": prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
            )
            for block in resp.content:
                if block.type == "tool_use":
                    return block.input
            return {}

        result = safe_call(_call, default={})
        return result if isinstance(result, dict) else {}

    def _search(self, agent: str, prompt: str, allowed: list[str] | None,
                uses: int) -> Finding:
        """Run a web search via Claude. Separates cited vs consulted sources."""
        def _call():
            tool = {"type": "web_search_20250305", "name": "web_search",
                    "max_uses": uses}
            if allowed:
                tool["allowed_domains"] = allowed
            return self.client.messages.create(
                model=MODEL, max_tokens=2500, system=GUARDRAIL,
                messages=[{"role": "user", "content": prompt}], tools=[tool],
            )

        resp = safe_call(_call, default=None)
        if resp is None:
            self._log(agent, "search failed — API error")
            return Finding(title="", body="Search unavailable.", agent=agent)

        body, cited, consulted = [], [], []
        for b in resp.content:
            if b.type == "text":
                body.append(b.text)
                for c in (getattr(b, "citations", None) or []):
                    cited.append(Source(
                        c.url, c.title or "",
                        getattr(c, "cited_text", "") or "", agent
                    ))
            elif (b.type == "web_search_tool_result"
                  and isinstance(b.content, list)):
                for r in b.content:
                    consulted.append(Source(r.url, r.title or "", "", agent))

        return Finding(
            title="", body="".join(body).strip(), agent=agent,
            sources=rank(cited), consulted=rank(consulted),
        )

    # ------------------------------------------------------------ IntakeAgent
    def extract_facts(self, case: CaseFile, answer: str) -> None:
        """Extract facts from user answer. Uses structured tool output online."""
        slot = case.pending_slot or "narrative"
        case.transcript.append({"role": "user", "text": answer})

        if not self.online:
            case.facts[slot] = answer
            self._log("IntakeAgent", f"filled {slot} (offline)")
            facts = {slot: answer}
        else:
            slots = [s for s, _ in case.question_queue()]
            data = self._ask_structured(
                "You extract facts from a legal intake answer.",
                f"Known facts: {json.dumps(case.facts)}\nSlots: {slots}\n"
                f"The person was asked about '{slot}'. Their answer: {answer!r}\n"
                "Only include slots the answer actually addresses. "
                "Use the person's words, no guessing.",
                EXTRACT_FACTS_TOOL,
            )
            facts = data.get("facts") or {slot: answer}
            case.facts.update({k: v for k, v in facts.items() if v})
            case.facts.setdefault(slot, answer)
            case.timeline.extend(data.get("timeline", []))

        # Post-extraction: normalize date and resolve entity
        from .intake import normalize_date, resolve_public_entity
        if "when" in case.facts and case.when_iso is None:
            result = normalize_date(case.facts["when"])
            case.when_iso = result.iso
            case.when_raw = result.raw
            if result.iso and result.confidence == "exact":
                case.facts["when"] = f"{result.iso} ({result.raw})"
                self._log("IntakeAgent", f"date normalized: {result.iso}")
            elif result.confidence == "vague":
                self._log("IntakeAgent", f"date is vague: '{result.raw}' — will ask for exact date")
        if ("public_entity" in case.facts
                and not case.resolved_entity
                and not case.entity_rejected):
            combined = " ".join([
                case.facts.get("narrative", ""),
                case.facts.get("where", ""),
                case.facts.get("public_entity", ""),
            ])
            resolved = resolve_public_entity(combined)
            if resolved:
                case.resolved_entity = resolved
                self._log("IntakeAgent", f"entity resolved: {resolved}")
        self._log("IntakeAgent", f"filled {', '.join(facts)}")

    # ------------------------------------------------------- ClassifierAgent
    def classify(self, case: CaseFile) -> None:
        """Classify law areas. Falls back to keyword baseline on any API failure."""
        text = " ".join(case.facts.values())
        base = baseline_classify(text)

        if not self.online:
            case.areas = base
            self._log("ClassifierAgent",
                       "keyword baseline: " + (", ".join(a.area for a in base) or "no signal yet"))
            return

        def _llm_classify():
            data = self._ask_structured(
                GUARDRAIL + "\nDo NOT include any statute citations in your reasoning.",
                f"Account of events:\n{case.summary_text()}\n\n"
                f"Areas: {list(LAW_AREAS)}\n"
                "Classify which areas of law apply. Max 3, ranked by relevance.",
                CLASSIFY_TOOL,
            )
            areas = []
            for a in data.get("areas", []):
                if a.get("area") in LAW_AREAS:
                    s = AreaScore(a["area"], float(a.get("score", 0)), [])
                    s.why = a.get("why", "")
                    areas.append(s)
            return areas if areas else None

        areas = safe_call(_llm_classify, default=None)
        if areas:
            case.areas = areas
            self._log("ClassifierAgent",
                       "areas: " + ", ".join(f"{a.area} {a.score:.0%}" for a in case.areas))
        else:
            case.areas = base
            self._log("ClassifierAgent",
                       "LLM failed, keyword fallback: " + ", ".join(a.area for a in base))

    # ---------------------------------------------------------- research run
    def research(self, case: CaseFile,
                 jurisdiction: str = "New York, NY") -> list[Finding]:
        """Dispatch StatuteAgent and ContextAgent in parallel, then validate.

        Uses ThreadPoolExecutor to run both agents concurrently.
        """
        self.findings = []
        area = case.primary_area or "General"

        if not self.online:
            self.findings = demo_findings(area)
            self._log("StatuteAgent", "offline demo findings loaded")
            self._log("ValidatorAgent", "validated demo set")
            return self.findings

        facts = case.summary_text()
        t_start = time.time()

        def _statute():
            t0 = time.time()
            self._log("StatuteAgent", f"searching primary law for {area} in {jurisdiction}")
            result = self._search(
                "StatuteAgent",
                f"Area: {area}. Jurisdiction: {jurisdiction}.\nFacts:\n{facts}\n\n"
                "Identify the statutes, regulations, municipal codes, and official "
                "procedures that govern a matter like this, including any filing or "
                "notice deadlines. Cite each one. Do NOT compute deadline dates — "
                "only state the rules.",
                STATUTE_DOMAINS, 4,
            )
            result.title = f"Governing law: {area}"
            self._log("StatuteAgent", f"done in {time.time() - t0:.1f}s")
            return result

        def _context():
            t0 = time.time()
            self._log("ContextAgent", "searching guides, news, and community context")
            result = self._search(
                "ContextAgent",
                f"Area: {area}. Jurisdiction: {jurisdiction}.\nFacts:\n{facts}\n\n"
                "Find plain language guides from legal aid or bar associations, "
                "recent news, and reputable explainer videos about this kind of "
                "matter. Label which are which.",
                None, 2,
            )
            result.title = "Plain language context"
            self._log("ContextAgent", f"done in {time.time() - t0:.1f}s")
            return result

        # Run agents in parallel
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_statute = pool.submit(_statute)
            fut_context = pool.submit(_context)
            self.findings.append(fut_statute.result())
            self.findings.append(fut_context.result())

        self._validate()
        self._log("Research", f"total wall time: {time.time() - t_start:.1f}s")
        return self.findings

    # -------------------------------------------------------- ValidatorAgent
    def _validate(self) -> None:
        """Validate findings using only cited sources (not all consulted)."""
        for f in self.findings:
            cited_tiers = {s.tier for s in f.sources}
            cited_with_text = [s for s in f.sources if s.snippet]
            if cited_with_text and (1 in cited_tiers or 2 in cited_tiers):
                f.status = "verified"
            elif 1 in cited_tiers or 2 in cited_tiers:
                f.status = "partial"
            elif 3 in cited_tiers:
                f.status = "partial"
            else:
                f.status = "unsupported"
            self._log("ValidatorAgent",
                       f"'{f.title}' {f.status.upper()} "
                       f"({len(f.sources)} cited, "
                       f"{len(f.consulted)} consulted, "
                       f"conf {f.score:.0%})")


def demo_findings(area: str) -> list[Finding]:
    """Offline sample so the HUD renders without an API key.

    Status is always 'unsupported' for demo data — never 'verified'.
    """
    s = lambda u, t, a: Source(u, t, "", a)
    return [
        Finding(
            title=f"[DEMO] Governing law: {area}",
            body=(
                "DEMO DATA — NOT REAL LAW. With an API key set, the "
                "StatuteAgent searches only government, court, and official "
                "code sources and cites each statute it names."
            ),
            agent="StatuteAgent", status="unsupported",
            sources=rank([
                s("https://www.nysenate.gov/legislation/laws/GMU/50-E",
                  "NY General Municipal Law 50-E", "StatuteAgent"),
                s("https://www.nycourts.gov/courthelp/",
                  "NY CourtHelp", "StatuteAgent"),
            ]),
        ),
        Finding(
            title="[DEMO] Plain language context",
            body=(
                "DEMO DATA — NOT REAL LAW. The ContextAgent gathers legal "
                "aid guides, news, and videos."
            ),
            agent="ContextAgent", status="unsupported",
            sources=rank([
                s("https://www.lawhelpny.org/", "LawHelpNY", "ContextAgent"),
            ]),
        ),
    ]
