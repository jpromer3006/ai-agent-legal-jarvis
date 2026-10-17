"""Live agent view: HUD-styled status cards for research agents.

Shows agent state (QUEUED → SEARCHING → CITING → DONE) with timers.
Updates via session state events pushed by the orchestrator.
"""
from __future__ import annotations

import html
import time


def esc(x: str) -> str:
    return html.escape(str(x))


AGENT_STATES = {
    "queued": {"color": "#5f8ea3", "label": "QUEUED", "icon": "◇"},
    "searching": {"color": "#ffb347", "label": "SEARCHING", "icon": "◈"},
    "reading": {"color": "#29e6ff", "label": "READING", "icon": "◉"},
    "citing": {"color": "#7ff3ff", "label": "CITING", "icon": "◎"},
    "validating": {"color": "#29e6ff", "label": "VALIDATING", "icon": "◈"},
    "done": {"color": "#3dffb5", "label": "DONE", "icon": "✓"},
    "error": {"color": "#ff4d6d", "label": "ERROR", "icon": "✗"},
}


def render_agent_cards(events: list[dict]) -> str:
    """Render HUD-styled agent status cards from event list.

    events: list of {agent, state, elapsed, queries[], sources_count, cited_count}
    Returns HTML string.
    """
    if not events:
        return ""

    cards = []
    for ev in events:
        agent = ev.get("agent", "Agent")
        state = ev.get("state", "queued")
        elapsed = ev.get("elapsed", 0)
        queries = ev.get("queries", [])
        src_count = ev.get("sources_count", 0)
        cited_count = ev.get("cited_count", 0)

        s = AGENT_STATES.get(state, AGENT_STATES["queued"])

        # Card
        card = (
            f'<div style="display:inline-block; border:1px solid {s["color"]}; '
            f'padding:8px 14px; margin:4px; min-width:180px; '
            f'background:rgba(6,28,44,.7); border-radius:3px; vertical-align:top;">'
            f'<div style="font-family:Orbitron,sans-serif; font-size:10px; '
            f'letter-spacing:.25em; color:{s["color"]};">'
            f'{s["icon"]} {esc(agent).upper()}</div>'
            f'<div style="font-family:Orbitron,sans-serif; font-size:11px; '
            f'letter-spacing:.2em; color:{s["color"]}; margin-top:4px;">'
            f'{s["label"]}</div>'
            f'<div style="font-size:10px; color:#5f8ea3; margin-top:3px;">'
            f'{elapsed:.1f}s</div>'
        )

        # Query feed
        if queries:
            last_q = queries[-1] if len(queries[-1]) < 50 else queries[-1][:47] + "..."
            card += (
                f'<div style="font-size:9px; color:#7ff3ff; margin-top:4px; '
                f'font-family:Share Tech Mono,monospace;">'
                f'→ {esc(last_q)}</div>'
            )

        # Source count
        if src_count or cited_count:
            card += (
                f'<div style="font-size:9px; color:#5f8ea3; margin-top:3px;">'
                f'{cited_count} cited · {src_count} consulted</div>'
            )

        card += '</div>'
        cards.append(card)

    return (
        '<div class="panel">'
        '<div class="ptitle">AGENT STATUS</div>'
        '<div style="display:flex; flex-wrap:wrap; gap:4px;">'
        + "".join(cards)
        + '</div></div>'
    )


def render_validator_summary(findings: list) -> str:
    """Render the final validator line: N consulted, N cited, N primary law."""
    total_cited = sum(len(f.sources) for f in findings)
    total_consulted = sum(len(getattr(f, "consulted", [])) for f in findings)
    primary = sum(1 for f in findings for s in f.sources if s.tier == 1)

    return (
        f'<div style="text-align:center; font-size:11px; color:#29e6ff; '
        f'letter-spacing:.15em; margin:8px 0; font-family:Orbitron,sans-serif;">'
        f'{total_consulted} CONSULTED · {total_cited} CITED · {primary} PRIMARY LAW'
        f'</div>'
    )
