"""Transparent firm workflow: who does what, and what is done.

Every step shows its status, WHO is responsible (JARVIS AI, Flashpoint,
the person, or a human at the firm), what was done, and what comes next.
AI never performs the human steps: conflict clearance, the consultation
decision, and engagement are always signed off by staff.

1. CLIENT INTAKE & EVALUATION
   1.1 Inquiry & Triage           JARVIS + Flashpoint (bilingual voice intake + verified survey)
   1.2 Conflict Check & Screening JARVIS screens, staff clears
   1.3 Initial Consultation       Attorney (Lawyer Mode) decides category and strategy
   1.4 Engagement                 Attorney + client (retainer, fees or fee waiver)
2. CASE SETUP & DATA GATHERING
   2.1 Matter Creation            JARVIS opens the matter after engagement
   2.2 Document Collection        Client uploads from a custom checklist
   2.3 Readiness Audit            JARVIS pre audit, paralegal confirms
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger("jarvis.workflow")
ROOT = Path(__file__).resolve().parent.parent
FIRM_FILE = ROOT / "data" / "firm_clients.json"

STEPS = [
    {"key": "triage", "phase": 1, "title": "Inquiry & Triage", "owner": "JARVIS AI + Flashpoint",
     "does": "Bilingual voice intake, dialect check, on the spot verification survey."},
    {"key": "conflict", "phase": 1, "title": "Conflict Check & Screening", "owner": "JARVIS screens · Staff clears",
     "does": "Names of other parties are checked against the firm's client list. Basic background gathered."},
    {"key": "consult", "phase": 1, "title": "Initial Consultation", "owner": "Attorney",
     "does": "Attorney reviews history, status and goals in Lawyer Mode and sets the category and strategy."},
    {"key": "engage", "phase": 1, "title": "Engagement", "owner": "Attorney + Client",
     "does": "Retainer agreement signed; fees paid or fee waiver noted."},
    {"key": "matter", "phase": 2, "title": "Matter Creation", "owner": "JARVIS AI",
     "does": "Matter number opened with the case file, language and stage."},
    {"key": "docs", "phase": 2, "title": "Document Collection", "owner": "Client",
     "does": "Custom checklist; uploads stay in the local matter folder."},
    {"key": "audit", "phase": 2, "title": "Readiness Audit", "owner": "JARVIS pre audit · Paralegal confirms",
     "does": "Missing or unusable files separated; red flags raised for staff."},
]

CATEGORIES = ["Removal defense", "Humanitarian (asylum, withholding, CAT)", "Family based",
              "Employment based", "Humanitarian (U visa, T visa, VAWA, SIJS)", "Naturalization", "Not yet decided"]


def default_state() -> dict:
    return {"conflict": {"status": "pending", "parties": [], "hits": [], "cleared_by": ""},
            "consult": {"status": "pending", "category": "", "attorney": "", "notes": ""},
            "engage": {"status": "pending", "retainer_signed": False, "fee": "", "fee_waiver": False},
            "matter": {"status": "pending", "id": ""},
            "docs": {"status": "pending", "uploads": {}},
            "audit": {"status": "pending", "results": {}, "confirmed_by": ""},
            "events": []}


def log_event(wf: dict, who: str, what: str) -> None:
    wf.setdefault("events", []).append({"t": datetime.now().strftime("%H:%M:%S"), "who": who, "what": what})


def status_of(key: str, case, wf: dict) -> str:
    """done | active | pending | flag"""
    if key == "triage":
        if case.stage_report:
            return "done" if case.stage_report.get("verified") else "flag"
        return "active"
    order = [s["key"] for s in STEPS]
    prev = order[order.index(key) - 1]
    prev_done = (status_of(prev, case, wf) == "done") if prev != "triage" else bool(case.stage_report)
    st = wf.get(key, {}).get("status", "pending")
    if st in ("done", "flag"):
        return st
    return "active" if prev_done else "pending"


# ---------------------------------------------------------------- conflicts
def load_firm_clients() -> list[dict]:
    try:
        return json.loads(FIRM_FILE.read_text())
    except Exception:
        return []


def _norm(n: str) -> str:
    return re.sub(r"[^a-z ]", "", n.lower()).strip()


def conflict_check(parties: list[str]) -> list[dict]:
    """Exact and close name matches against current and former clients and adverse parties."""
    hits = []
    firm = load_firm_clients()
    for p in parties:
        pn = _norm(p)
        if not pn:
            continue
        ptoks = set(pn.split())
        for rec in firm:
            for field in ("client", "adverse"):
                rn = _norm(rec.get(field, ""))
                if not rn:
                    continue
                rtoks = set(rn.split())
                if pn == rn or (len(ptoks & rtoks) >= 2):
                    hits.append({"party": p, "matched": rec.get(field), "as": field,
                                 "matter": rec.get("matter", ""), "exact": pn == rn})
    return hits


# ---------------------------------------------------------------- matter
def matter_id(case) -> str:
    lang_code = {"English": "EN", "Spanish": "ES", "Georgian": "KA", "Egyptian Arabic": "AR"}.get(case.language, "XX")
    stage = (case.stage_report or {}).get("stage", "na").upper()[:5]
    return f"IMM-{date.today():%Y%m%d}-{lang_code}-{stage}-{case.folder.name[-4:].upper()}"


# ---------------------------------------------------------------- documents
BASE_DOCS = [
    ("passport", "Passport (all pages with stamps) or national ID", True),
    ("i94", "I-94 arrival record, or any entry document", True),
    ("birth_cert", "Birth certificate", True),
    ("notices", "All letters from USCIS or the immigration court (I-797, Notice to Appear, hearing notices)", True),
    ("address_proof", "Proof of current address (lease, utility bill, letter)", False),
]
CATEGORY_DOCS = {
    "Removal defense": [("nta", "Notice to Appear (NTA) and every hearing notice", True),
                        ("prior_orders", "Any prior immigration judge order or decision", False)],
    "Humanitarian (asylum, withholding, CAT)": [
        ("i589_draft", "Any asylum application already prepared (I-589)", False),
        ("persecution_evidence", "Evidence of harm or threats (reports, photos, medical records, letters)", True),
        ("country_id", "Identity proof from home country", True)],
    "Family based": [("relative_status", "Proof of the U.S. relative's status (passport, green card, naturalization)", True),
                     ("relationship", "Proof of relationship (marriage or birth certificate)", True),
                     ("tax_returns", "Tax returns or transcripts, last 3 years (for the sponsor)", True)],
    "Employment based": [("job_offer", "Job offer or employer letter", True),
                         ("degrees", "Diplomas and transcripts", True),
                         ("tax_returns", "Tax returns or W-2s, last 3 years", False)],
    "Humanitarian (U visa, T visa, VAWA, SIJS)": [("cert", "Law enforcement certification (I-918 Supplement B) if any", False),
                                                    ("police_reports", "Police or court reports", False)],
    "Naturalization": [("green_card", "Green card (front and back)", True),
                       ("travel", "List of trips outside the U.S.", True),
                       ("tax_returns", "Tax transcripts, last 5 years", True)],
}
TRANSLATION_DOC = ("translations", "Certified English translations of any document not in English (8 C.F.R. § 103.2(b)(3))", True)


def checklist(case, category: str) -> list[tuple[str, str, bool]]:
    items = list(BASE_DOCS) + CATEGORY_DOCS.get(category, [])
    if case.language != "English":
        items.append(TRANSLATION_DOC)
    if (case.stage_report or {}).get("stage") in ("court", "decision", "appeal") and category != "Removal defense":
        items += CATEGORY_DOCS["Removal defense"]
    seen, out = set(), []
    for it in items:
        if it[0] not in seen:
            seen.add(it[0])
            out.append(it)
    return out


AUDIT_TOOL = {
    "name": "document_audit",
    "description": "Pre audit of one uploaded immigration document for a paralegal.",
    "input_schema": {"type": "object", "properties": {
        "matches_expected": {"type": "boolean"},
        "detected_type": {"type": "string"},
        "legible": {"type": "boolean"},
        "language": {"type": "string"},
        "needs_certified_translation": {"type": "boolean"},
        "expiration_date": {"type": "string", "description": "YYYY-MM-DD or empty"},
        "red_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 5,
                      "description": "Only document quality issues: expired, cut off, missing pages, "
                                     "name spelling differs, blurry, wrong document. Never judge eligibility or credibility."},
        "summary": {"type": "string"}},
        "required": ["matches_expected", "detected_type", "legible", "red_flags", "summary"]},
}


def audit_document(path: Path, expected: str, client_name_hint: str = "") -> dict:
    """Claude vision pre audit. Never stores or repeats ID numbers."""
    key = os.getenv("ANTHROPIC_API_KEY")
    suffix = path.suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".pdf"):
        return {"matches_expected": False, "detected_type": suffix, "legible": False,
                "red_flags": ["Unsupported file type; upload PDF or a photo"], "summary": "Unusable file type."}
    if path.stat().st_size == 0:
        return {"matches_expected": False, "detected_type": "empty", "legible": False,
                "red_flags": ["Empty file"], "summary": "Empty upload."}
    if not key:
        return {"matches_expected": True, "detected_type": "unchecked", "legible": True,
                "red_flags": [], "summary": "Offline: received, not audited."}
    try:
        import anthropic
        data = base64.b64encode(path.read_bytes()).decode()
        block = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
                 if suffix == ".pdf" else
                 {"type": "image", "source": {"type": "base64",
                                              "media_type": "image/jpeg" if suffix in (".jpg", ".jpeg") else f"image/{suffix[1:]}",
                                              "data": data}})
        resp = anthropic.Anthropic(api_key=key).messages.create(
            model=os.getenv("JARVIS_FAST_MODEL", "claude-haiku-4-5-20251001"), max_tokens=800,
            system=("You pre audit documents for an immigration law paralegal. Check only document "
                    "quality and completeness. Never output ID numbers, A-numbers, or dates of birth. "
                    f"Today is {date.today():%Y-%m-%d}."),
            messages=[{"role": "user", "content": [block, {"type": "text", "text":
                       f"Expected document: {expected}. Client name on file (for spelling check): "
                       f"{client_name_hint or 'not given'}."}]}],
            tools=[AUDIT_TOOL], tool_choice={"type": "tool", "name": "document_audit"})
        for b in resp.content:
            if b.type == "tool_use":
                out = dict(b.input)
                exp = out.get("expiration_date") or ""
                try:
                    if (exp and date.fromisoformat(exp) < date.today()
                            and not any("xpir" in f for f in out.get("red_flags", []))):
                        out.setdefault("red_flags", []).append(f"Expired on {exp}")
                except ValueError:
                    pass
                return out
    except Exception as e:
        logger.warning("audit failed: %s", e)
        return {"matches_expected": False, "detected_type": "error", "legible": False,
                "red_flags": [f"Audit error: {e}"], "summary": "Could not audit; review manually."}
    return {"matches_expected": False, "detected_type": "unknown", "legible": False,
            "red_flags": ["No audit result"], "summary": "Review manually."}


ENGAGEMENT_TEMPLATE = """DRAFT FOR ATTORNEY REVIEW · NOT A SIGNED AGREEMENT

LIMITED SCOPE ENGAGEMENT SUMMARY
Matter: {matter}
Client language: {language} (interpreter or translation provided: {interp})
Category: {category}
Procedural stage at intake: {stage}

Scope of representation (attorney to complete):
  [ ] {category}
  [ ] Forms likely involved: {forms}
Fees: {fee}   Fee waiver or pro bono: {waiver}

The client was informed in {language} that:
  • The intake assistant (JARVIS) provides information only, not legal advice.
  • Only an attorney or a DOJ accredited representative can give legal advice.
  • Notarios and form preparers are not lawyers in the U.S.

Attorney: ____________________   Client: ____________________   Date: __________
"""
