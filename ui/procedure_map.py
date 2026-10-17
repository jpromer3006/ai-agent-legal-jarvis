"""Legal Procedure Map: SVG visual stepper for JARVIS dashboard.

Renders an inline SVG timeline showing where the user is in the legal
process. Matches the HUD theme (Orbitron, Share Tech Mono, cyan #29e6ff).

Node states:
  done    — filled cyan circle with checkmark
  current — pulsing glow ring with "YOU ARE HERE" tag
  upcoming — hollow dimmed circle
  unknown  — dashed outline

Deadline chips show date + days remaining; amber < 30 days, red when expired.
Branches drawn as small side paths below the main timeline.
"""
from __future__ import annotations

import html

from core.procedure import ProcedureResult, StageStatus


def esc(x: str) -> str:
    return html.escape(str(x))


def render_procedure_map(result: ProcedureResult, selected_stage: int = -1) -> str:
    """Render the full procedure map as HTML (SVG + detail card).

    selected_stage: index of stage to show detail for (-1 = current stage).
    Returns HTML string for st.html() or st.markdown(unsafe_allow_html=True).
    """
    stages = result.stages
    n = len(stages)
    if n == 0:
        return ""

    if selected_stage < 0:
        selected_stage = result.current_index if result.current_index >= 0 else 0

    # Layout constants
    node_r = 18
    spacing = 110
    padding = 60
    svg_w = padding * 2 + spacing * (n - 1)
    svg_h = 160
    cy = 55  # vertical center of nodes

    # Build SVG
    svg_parts = [
        f'<svg viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%; max-width:{svg_w}px; height:auto; overflow:visible;">',
        '<defs>',
        '  <filter id="pm-glow"><feGaussianBlur stdDeviation="3" result="b"/>'
        '  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '  <filter id="pm-pulse"><feGaussianBlur stdDeviation="5" result="b"/>'
        '  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '</defs>',
    ]

    # Connection lines
    for i in range(n - 1):
        x1 = padding + i * spacing + node_r
        x2 = padding + (i + 1) * spacing - node_r
        s = stages[i]
        color = "#29e6ff" if s.status == "done" else "#1a3a4a"
        width = 3 if s.status == "done" else 2
        dash = "" if s.status == "done" else ' stroke-dasharray="6 4"'
        svg_parts.append(
            f'<line x1="{x1}" y1="{cy}" x2="{x2}" y2="{cy}" '
            f'stroke="{color}" stroke-width="{width}"{dash} opacity=".7"/>'
        )

    # Nodes
    for i, ss in enumerate(stages):
        cx = padding + i * spacing
        stage = ss.stage

        if ss.status == "done":
            # Filled cyan circle with checkmark
            svg_parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node_r}" '
                f'fill="rgba(41,230,255,.2)" stroke="#29e6ff" stroke-width="2.5" '
                f'filter="url(#pm-glow)"/>'
            )
            svg_parts.append(
                f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" '
                f'font-size="16" fill="#29e6ff" font-weight="bold">&#10003;</text>'
            )
        elif ss.status == "current":
            # Pulsing glow ring
            svg_parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node_r + 6}" '
                f'fill="none" stroke="#29e6ff" stroke-width="2" opacity=".3">'
                f'<animate attributeName="r" values="{node_r+4};{node_r+10};{node_r+4}" '
                f'dur="2s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values=".5;.15;.5" '
                f'dur="2s" repeatCount="indefinite"/>'
                f'</circle>'
            )
            svg_parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node_r}" '
                f'fill="rgba(41,230,255,.15)" stroke="#7ff3ff" stroke-width="3" '
                f'filter="url(#pm-pulse)"/>'
            )
            svg_parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="5" fill="#29e6ff">'
                f'<animate attributeName="r" values="4;6;4" dur="1.5s" repeatCount="indefinite"/>'
                f'</circle>'
            )
            # "YOU ARE HERE" tag
            svg_parts.append(
                f'<rect x="{cx - 42}" y="{cy - node_r - 22}" width="84" height="16" '
                f'rx="2" fill="rgba(41,230,255,.15)" stroke="#29e6ff" stroke-width="1"/>'
            )
            svg_parts.append(
                f'<text x="{cx}" y="{cy - node_r - 10}" text-anchor="middle" '
                f'font-family="Orbitron,sans-serif" font-size="8" fill="#29e6ff" '
                f'letter-spacing=".15em">YOU ARE HERE</text>'
            )
        elif ss.status == "upcoming":
            # Hollow dimmed circle
            svg_parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node_r}" '
                f'fill="none" stroke="#1a3a4a" stroke-width="2"/>'
            )
        else:
            # Unknown — dashed
            svg_parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node_r}" '
                f'fill="none" stroke="#1a3a4a" stroke-width="2" '
                f'stroke-dasharray="4 3"/>'
            )

        # Stage title below node — wrap long titles across two lines
        title = esc(stage["title"])
        fill = "#29e6ff" if ss.status in ("done", "current") else "#3a5a6a"
        if len(title) > 16:
            # Split into two lines at a natural break
            mid = len(title) // 2
            split = title.rfind(" ", 0, mid + 4)
            if split < 3:
                split = title.find(" ", mid)
            if split > 0:
                line1, line2 = title[:split], title[split + 1:]
            else:
                line1, line2 = title[:14], title[14:]
            svg_parts.append(
                f'<text x="{cx}" y="{cy + node_r + 15}" text-anchor="middle" '
                f'font-family="Share Tech Mono,monospace" font-size="11" '
                f'fill="{fill}" letter-spacing=".03em">{line1}</text>'
            )
            svg_parts.append(
                f'<text x="{cx}" y="{cy + node_r + 27}" text-anchor="middle" '
                f'font-family="Share Tech Mono,monospace" font-size="11" '
                f'fill="{fill}" letter-spacing=".03em">{line2}</text>'
            )
        else:
            svg_parts.append(
                f'<text x="{cx}" y="{cy + node_r + 16}" text-anchor="middle" '
                f'font-family="Share Tech Mono,monospace" font-size="11" '
                f'fill="{fill}" letter-spacing=".03em">{title}</text>'
            )

        # Deadline chip
        if ss.deadline_date:
            chip_color = "#ff4d6d" if ss.is_expired else (
                "#ffb347" if ss.days_remaining is not None and ss.days_remaining < 30
                else "#29e6ff"
            )
            days_text = ("EXPIRED" if ss.is_expired
                         else f"{ss.days_remaining}d" if ss.days_remaining is not None
                         else "")
            svg_parts.append(
                f'<rect x="{cx - 30}" y="{cy + node_r + 22}" width="60" height="14" '
                f'rx="2" fill="rgba(0,0,0,.4)" stroke="{chip_color}" stroke-width="1"/>'
            )
            svg_parts.append(
                f'<text x="{cx}" y="{cy + node_r + 32}" text-anchor="middle" '
                f'font-family="Orbitron,sans-serif" font-size="7" fill="{chip_color}">'
                f'{days_text}</text>'
            )

        # Branches (small side paths below)
        for j, branch in enumerate(stage.get("branches", []) if isinstance(stage, dict) else []):
            bx = cx
            by = cy + node_r + 45 + j * 18
            svg_parts.append(
                f'<line x1="{cx}" y1="{cy + node_r + 2}" x2="{bx}" y2="{by - 6}" '
                f'stroke="#5f8ea3" stroke-width="1" stroke-dasharray="3 2"/>'
            )
            svg_parts.append(
                f'<circle cx="{bx}" cy="{by}" r="4" fill="none" '
                f'stroke="#5f8ea3" stroke-width="1"/>'
            )
            btitle = esc(branch.get("title", "")[:16])
            svg_parts.append(
                f'<text x="{bx + 8}" y="{by + 3}" font-family="Share Tech Mono,monospace" '
                f'font-size="7" fill="#5f8ea3">{btitle}</text>'
            )

    svg_parts.append('</svg>')
    svg_html = "\n".join(svg_parts)

    # Detail card for selected stage
    sel = stages[selected_stage] if 0 <= selected_stage < n else None
    detail_html = ""
    if sel:
        stage = sel.stage
        detail_html = _render_detail_card(sel)

    # IMPORTANT: no leading whitespace — st.markdown treats indented HTML as code
    return (
'<div class="panel" style="overflow-x:auto;">'
'<div class="ptitle">LEGAL PROCEDURE MAP'
f' <span>{esc(result.procedure.get("title", ""))}</span></div>'
f'<div style="overflow-x:auto; padding:10px 0;">{svg_html}</div>'
f'{detail_html}'
'<div class="disclaimer" style="margin-top:8px;">'
'This is an educational overview of a typical legal process. '
'It is not legal advice. Confirm all steps with a licensed attorney or legal aid.'
'</div></div>'
    )


def _render_detail_card(ss: StageStatus) -> str:
    """Render the detail card for a selected stage. No leading whitespace."""
    stage = ss.stage
    parts = []

    status_color = {
        "done": "#3dffb5", "current": "#29e6ff",
        "upcoming": "#5f8ea3", "unknown": "#5f8ea3",
    }.get(ss.status, "#5f8ea3")
    status_label = {
        "done": "COMPLETED", "current": "CURRENT STAGE",
        "upcoming": "UPCOMING", "unknown": "UNKNOWN",
    }.get(ss.status, "")

    parts.append(
        f'<div style="border-top:1px solid rgba(41,230,255,.2); margin-top:12px; padding-top:12px;">'
        f'<div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">'
        f'<span style="font-family:Orbitron,sans-serif; font-size:13px; color:#29e6ff; '
        f'letter-spacing:.15em;">{esc(stage["title"]).upper()}</span>'
        f'<span style="font-size:9px; padding:2px 8px; border:1px solid {status_color}; '
        f'color:{status_color}; letter-spacing:.1em; border-radius:2px;">{status_label}</span>'
        f'</div>'
        f'<div style="font-size:13px; color:#e9fbff; line-height:1.5; margin-bottom:8px;">'
        f'{esc(stage.get("plain", ""))}</div>'
    )

    if ss.deadline_date:
        dl_color = "#ff4d6d" if ss.is_expired else "#ffb347"
        days = "EXPIRED" if ss.is_expired else f"{ss.days_remaining} days remaining"
        parts.append(
            f'<div style="border:1px solid {dl_color}; padding:6px 10px; margin:6px 0; '
            f'background:rgba(255,179,71,.06); font-size:12px;">'
            f'<span style="color:{dl_color}; font-family:Orbitron,sans-serif; '
            f'font-size:11px; letter-spacing:.1em;">DEADLINE: {esc(ss.deadline_date)}</span>'
            f'<span style="color:{dl_color}; margin-left:8px;">{days}</span></div>'
        )
        if ss.is_expired:
            parts.append(
                '<div style="font-size:11px; color:#ff4d6d; margin:4px 0;">'
                'Contact a licensed attorney, legal aid, or a court help center now. '
                'Other paths may exist.</div>'
            )

    anticipate = stage.get("anticipate", [])
    if anticipate:
        items = "".join(f'<li style="margin:3px 0;">{esc(a)}</li>' for a in anticipate)
        parts.append(
            '<div style="font-size:11px; color:#5f8ea3; letter-spacing:.1em; margin-top:8px;">'
            'WHAT TO ANTICIPATE</div>'
            f'<ul style="font-size:12px; color:#d8f6ff; margin:4px 0 8px 16px; padding:0;">{items}</ul>'
        )

    docs = stage.get("documents", [])
    if docs:
        items = "".join(f'<li style="margin:2px 0;">{esc(d)}</li>' for d in docs)
        parts.append(
            '<div style="font-size:11px; color:#5f8ea3; letter-spacing:.1em;">'
            'DOCUMENTS TO GATHER</div>'
            f'<ul style="font-size:12px; color:#d8f6ff; margin:4px 0 8px 16px; padding:0;">{items}</ul>'
        )

    who = stage.get("who_you_deal_with", [])
    if who:
        parts.append(
            '<div style="font-size:11px; color:#5f8ea3; letter-spacing:.1em;">'
            'WHO YOU TYPICALLY DEAL WITH</div>'
            f'<div style="font-size:12px; color:#d8f6ff; margin:4px 0 8px;">'
            f'{", ".join(esc(w) for w in who)}</div>'
        )

    sources = stage.get("sources", [])
    if sources:
        src_html = "".join(
            f'<a href="{esc(s["url"])}" target="_blank" '
            f'style="color:#29e6ff; font-size:11px; margin-right:12px;">'
            f'{esc(s["label"])}</a>'
            for s in sources
        )
        parts.append(
            '<div style="font-size:11px; color:#5f8ea3; letter-spacing:.1em;">SOURCES</div>'
            f'<div style="margin:4px 0 8px;">{src_html}</div>'
        )

    dur = stage.get("typical_duration")
    if dur:
        parts.append(
            f'<div style="font-size:11px; color:#5f8ea3; margin-top:4px;">'
            f'TYPICAL DURATION: <span style="color:#d8f6ff;">{esc(dur)}</span></div>'
        )

    parts.append('</div>')
    return "".join(parts)
