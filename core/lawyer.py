"""Lawyer Mode: IRAC memo generation, Claude Legal research, PDF export.

Transforms Jarvis intake + agent findings into a professional legal memo
using the IRAC framework (Issue, Rule, Application, Conclusion) with
footnoted sources linked for easy retrieval.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = os.getenv("JARVIS_MODEL", "claude-sonnet-5-5")

LAWYER_SYSTEM = """You are Claude Legal, an AI legal research assistant operating in Lawyer Mode.
You have access to web search and can research case law, statutes, and legal commentary.
You speak precisely, citing sources. You assist licensed attorneys with research and analysis.
You do NOT give legal advice to end clients — you assist the lawyer's own analysis.
When citing cases, use standard legal citation format (Bluebook).
When discussing statutes, cite the full section reference.
Always note jurisdictional limitations."""

IRAC_SYSTEM = """You are Claude Legal generating an IRAC memorandum for an attorney.
Structure the memo EXACTLY as follows:

MEMORANDUM OF LAW

TO: [Attorney]
FROM: Claude Legal Research Assistant
DATE: [today]
RE: [case summary in one line]

I. ISSUE(S) PRESENTED
State each legal issue as a question.

II. RULE(S) OF LAW
State the governing statutes, regulations, and case law. Cite everything.

III. APPLICATION
Apply the rules to the specific facts of this case. Analyze strengths and weaknesses.
Reference specific facts from the intake. Discuss analogous cases if relevant.

IV. POSSIBLE OUTCOMES AND OPEN QUESTIONS
State possible outcomes, open questions, and areas needing further research.

V. SOURCES
List every source cited, numbered as footnotes. Each source MUST include:
  [n] Title — https://full.url.here
Example:
  [1] NY GML §50-e — https://www.nysenate.gov/legislation/laws/GMU/50-E
  [2] NYC Comptroller Claims FAQ — https://comptroller.nyc.gov/claims/

RULES:
- Use footnote markers [1], [2], etc. inline when citing sources
- Every legal claim must have a citation
- Every footnote in SOURCES must include the full https:// URL
- Be thorough but concise
- Note any gaps in the research or areas needing further investigation
- Include both favorable and unfavorable authority
- Flag any jurisdictional issues
"""


def claude_legal_chat(messages: list[dict], system: str = "",
                      web_search: bool = True) -> tuple[str, list[dict]]:
    """Chat with Claude Legal, optionally with web search.

    Returns (response_text, sources) where sources is a list of
    {"url": str, "title": str} dicts from web search results.
    """
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or anthropic is None:
        return "Claude Legal requires ANTHROPIC_API_KEY.", []

    client = anthropic.Anthropic(api_key=key)
    tools = []
    if web_search:
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]

    resp = client.messages.create(
        model=MODEL, max_tokens=8000, system=system or LAWYER_SYSTEM,
        messages=messages, tools=tools if tools else anthropic.NOT_GIVEN,
    )

    body_parts = []
    sources = []
    for block in resp.content:
        if block.type == "text":
            body_parts.append(block.text)
            for cite in (getattr(block, "citations", None) or []):
                sources.append({"url": cite.url, "title": cite.title or ""})
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):
            for r in block.content:
                sources.append({"url": r.url, "title": r.title or ""})

    # Dedupe sources
    seen = set()
    unique = []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)

    return "".join(body_parts).strip(), unique


def generate_irac_memo(case_summary: str, findings: list[dict],
                       sources: list[dict], attorney_name: str = "Attorney",
                       prior_discussion: list[dict] | None = None) -> str:
    """Generate an IRAC memo using Claude with all case context.

    findings: list of {"title": str, "body": str, "sources": [{"url","title"}]}
    sources: all accumulated sources from research + chat
    prior_discussion: lawyer's chat messages for additional context
    """
    # Build context
    findings_text = "\n\n".join(
        f"### {f['title']}\n{f['body']}\nSources: " +
        ", ".join(s.get("title", s.get("url", "")) for s in f.get("sources", [])[:5])
        for f in findings
    )

    source_list = "\n".join(
        f"[{i+1}] {s.get('title', 'Untitled')} — {s['url']}"
        for i, s in enumerate(sources)
    )

    discussion_ctx = ""
    if prior_discussion:
        discussion_ctx = "\n\nPRIOR ATTORNEY DISCUSSION:\n" + "\n".join(
            f"{'ATTORNEY' if m['role'] == 'user' else 'CLAUDE LEGAL'}: {m['content']}"
            for m in prior_discussion
        )

    prompt = (
        f"Generate a complete IRAC memorandum based on the following:\n\n"
        f"CASE FACTS:\n{case_summary}\n\n"
        f"RESEARCH FINDINGS:\n{findings_text}\n\n"
        f"AVAILABLE SOURCES (use these for footnotes):\n{source_list}\n"
        f"{discussion_ctx}\n\n"
        f"Attorney name: {attorney_name}\n"
        f"Date: {datetime.now().strftime('%B %d, %Y')}\n\n"
        f"Generate the IRAC memo now. Rules for sources:\n"
        f"1. Use [n] footnote markers inline whenever citing a source.\n"
        f"2. In the V. SOURCES section, list EVERY cited source as:\n"
        f"   [n] Title — full URL\n"
        f"   Example: [1] NY GML §50-e — https://www.nysenate.gov/legislation/laws/GMU/50-E\n"
        f"3. Every footnote MUST include the full https:// URL.\n"
        f"4. Do not omit URLs. The reader needs clickable links to verify each source.\n"
        f"5. ALWAYS include the V. SOURCES section at the end. It is mandatory.\n"
        f"6. Keep analysis concise so there is room for the full SOURCES section."
    )

    text, extra_sources = claude_legal_chat(
        [{"role": "user", "content": prompt}],
        system=IRAC_SYSTEM, web_search=True
    )

    return text


def memo_to_pdf(memo_text: str, case_title: str = "Legal Memorandum") -> bytes:
    """Convert IRAC memo text to a professional PDF. Returns PDF bytes."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    )
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=1.2 * inch, rightMargin=1.2 * inch,
        topMargin=1 * inch, bottomMargin=1 * inch,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "MemoTitle", parent=styles["Title"],
        fontSize=16, spaceAfter=6, textColor=HexColor("#1a1a2e"),
        fontName="Times-Bold",
    ))
    styles.add(ParagraphStyle(
        "MemoHeading", parent=styles["Heading2"],
        fontSize=12, spaceBefore=16, spaceAfter=8,
        textColor=HexColor("#1a1a2e"), fontName="Times-Bold",
    ))
    styles.add(ParagraphStyle(
        "MemoBody", parent=styles["Normal"],
        fontSize=11, leading=15, spaceAfter=8,
        alignment=TA_JUSTIFY, fontName="Times-Roman",
    ))
    styles.add(ParagraphStyle(
        "MemoHeader", parent=styles["Normal"],
        fontSize=10, leading=14, spaceAfter=2,
        fontName="Times-Roman", textColor=HexColor("#333333"),
    ))
    styles.add(ParagraphStyle(
        "Footnote", parent=styles["Normal"],
        fontSize=9, leading=12, spaceAfter=4,
        fontName="Times-Roman", textColor=HexColor("#0055aa"),
    ))
    styles.add(ParagraphStyle(
        "Confidential", parent=styles["Normal"],
        fontSize=8, alignment=TA_CENTER,
        textColor=HexColor("#999999"), fontName="Times-Italic",
    ))

    story = []

    # Confidential header
    story.append(Paragraph("EDUCATIONAL DEMO — NOT LEGAL ADVICE", styles["Confidential"]))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#1a1a2e")))
    story.append(Spacer(1, 8))

    # Parse memo into sections
    lines = memo_text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "---":
            story.append(Spacer(1, 6))
            continue

        # Strip markdown formatting for PDF
        clean = stripped
        clean = re.sub(r"^#{1,4}\s+", "", clean)  # ## headings
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)  # **bold**
        clean = re.sub(r"\*(.+?)\*", r"\1", clean)  # *italic*

        # Detect headings
        if clean.startswith("MEMORANDUM OF LAW"):
            story.append(Paragraph(clean, styles["MemoTitle"]))
            continue
        if re.match(r"^(I{1,3}V?|V)\.\s", clean) or clean.startswith("V. SOURCES"):
            story.append(Spacer(1, 8))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc")))
            story.append(Paragraph(clean, styles["MemoHeading"]))
            continue
        if clean.startswith(("TO:", "FROM:", "DATE:", "RE:")):
            story.append(Paragraph(clean, styles["MemoHeader"]))
            continue

        # Any line with a URL — make it clickable
        url_match = re.search(r'(https?://\S+)', clean)
        if url_match:
            url = url_match.group(1).rstrip(".,;)")
            # Escape the non-URL parts for XML safety
            before = clean[:url_match.start()]
            after = clean[url_match.start() + len(url_match.group(1)):]
            safe_before = before.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            safe_after = after.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # Bold footnote refs in the before text
            safe_before = re.sub(r'\[(\d+)\]', r'<b>[\1]</b>', safe_before)
            display = f'{safe_before}<a href="{url}" color="#0055aa">{url}</a>{safe_after}'
            story.append(Paragraph(display, styles["Footnote"]))
            continue

        # Regular body text — escape XML entities
        safe = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Bold footnote refs
        safe = re.sub(r'\[(\d+)\]', r'<b>[\1]</b>', safe)
        story.append(Paragraph(safe, styles["MemoBody"]))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#1a1a2e")))
    story.append(Paragraph(
        f"Generated by JARVIS Legal OS — Claude Legal Research · {datetime.now().strftime('%B %d, %Y %H:%M')}",
        styles["Confidential"]
    ))

    doc.build(story)
    return buf.getvalue()
