"""Workflow tracker: every step, its owner, and its status, always visible."""
from __future__ import annotations

import html

from core.workflow import STEPS, status_of

ICON = {"done": "✓", "active": "●", "pending": "○", "flag": "!"}
COLOR = {"done": "#39ff9f", "active": "#29e6ff", "pending": "#3c6577", "flag": "#ffb347"}


def render_tracker(case, wf: dict) -> str:
    cells = ""
    for i, s in enumerate(STEPS):
        st = status_of(s["key"], case, wf)
        c = COLOR[st]
        sep = '<div style="width:10px"></div>' if i == 3 else ""
        cells += (f'<div style="flex:1;border:1px solid {c};padding:6px 8px;background:rgba(41,230,255,.03)">'
                  f'<div style="font-size:9px;letter-spacing:.2em;color:#5f8ea3">{"INTAKE &amp; EVALUATION" if s["phase"] == 1 else "CASE SETUP &amp; DATA"}</div>'
                  f'<div style="font-size:11.5px;color:{c};letter-spacing:.06em">{ICON[st]} {html.escape(s["title"]).upper()}</div>'
                  f'<div style="font-size:10px;color:#9fc7d6">{html.escape(s["owner"])}</div></div>{sep}')
    return f'<div style="display:flex;gap:6px;margin:4px 0 10px">{cells}</div>'


def render_events(wf: dict) -> str:
    ev = wf.get("events", [])
    if not ev:
        return '<div class="log">No workflow events yet.</div>'
    return "".join(f'<div class="log">{html.escape(e["t"])} <b>{html.escape(e["who"])}</b> {html.escape(e["what"])}</div>'
                   for e in reversed(ev[-30:]))
