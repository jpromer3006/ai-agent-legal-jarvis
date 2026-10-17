"""CourtListener API integration for case citation verification.

Uses CourtListener v4 API to verify case citations extracted from
IRAC memos. Requires COURTLISTENER env var with API token.
"""
from __future__ import annotations

import os
import re
import logging

logger = logging.getLogger("jarvis.courtlistener")

CL_BASE = "https://www.courtlistener.com/api/rest/v4"


def _get_token() -> str | None:
    return os.getenv("COURTLISTENER")


def search_citation(citation: str) -> dict | None:
    """Search CourtListener for a case citation.

    Returns {"url", "case_name", "citation", "verified": True} or None.
    """
    token = _get_token()
    if not token:
        logger.warning("COURTLISTENER token not set")
        return None

    try:
        import urllib.request
        import urllib.parse
        import json

        query = urllib.parse.quote(citation)
        url = f"{CL_BASE}/search/?q={query}&type=o"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Token {token}",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            if results:
                r = results[0]
                return {
                    "citation": citation,
                    "case_name": r.get("caseName", ""),
                    "url": f"https://www.courtlistener.com{r.get('absolute_url', '')}",
                    "verified": True,
                }
        return None
    except Exception as e:
        logger.warning("CourtListener search failed: %s", e)
        return None


def extract_case_citations(text: str) -> list[str]:
    """Extract case citations from text using common legal citation patterns.

    Matches patterns like:
      - Name v. Name, 123 N.Y.3d 456 (2025)
      - Name v. Name, 123 F.3d 456 (2d Cir. 2025)
      - Name v. Name, No. 12-3456
    """
    patterns = [
        r'[A-Z][a-zA-Z\.\s]+v\.\s+[A-Z][a-zA-Z\.\s]+,\s*\d+\s+[A-Z][A-Za-z\.]+\s*\d+\s*(?:\([^)]+\))?',
        r'[A-Z][a-zA-Z\.\s]+v\.\s+[A-Z][a-zA-Z\.\s]+,\s*No\.\s*[\d\-]+',
    ]
    citations = []
    for pat in patterns:
        for match in re.finditer(pat, text):
            cite = match.group(0).strip().rstrip(",.")
            if cite not in citations and len(cite) > 10:
                citations.append(cite)
    return citations


def verify_memo_citations(memo_text: str) -> list[dict]:
    """Extract and verify all case citations in an IRAC memo.

    Returns list of {"citation", "case_name", "url", "verified": bool}
    """
    citations = extract_case_citations(memo_text)
    results = []
    for cite in citations:
        cl_result = search_citation(cite)
        if cl_result:
            results.append(cl_result)
        else:
            results.append({
                "citation": cite,
                "case_name": "",
                "url": "",
                "verified": False,
            })
    return results
