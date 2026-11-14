"""HUD components for JARVIS Immigration: procedure stepper, rules, forms."""
from __future__ import annotations

import html

from core.immigration import CONCERNS, FORMS, LOOKUPS, RULES, STAGES, STAGE_INDEX


def esc(x) -> str:
    return html.escape(str(x))


CSS = """
<style>
.stepper{display:flex; gap:6px; margin:6px 0 12px;}
.step{flex:1; border:1px solid rgba(41,230,255,.25); padding:8px 6px; text-align:center;
  font-size:10px; letter-spacing:.12em; color:#5f8ea3; background:rgba(41,230,255,.03);}
.step.done{color:#9fe8ff; border-color:rgba(41,230,255,.45);}
.step.now{color:#01060c; background:#29e6ff; border-color:#29e6ff; font-weight:700;
  box-shadow:0 0 18px rgba(41,230,255,.6);}
.alert{padding:8px 10px; margin:6px 0; font-size:13px; border-left:3px solid;}
.alert.urgent{border-color:#ff4d6d; background:rgba(255,77,109,.10); color:#ffd3db;}
.alert.warning{border-color:#ffb347; background:rgba(255,179,71,.08); color:#ffe6c2;}
.alert.info{border-color:#29e6ff; background:rgba(41,230,255,.06); color:#d8f6ff;}
.rule{font-size:12.5px; padding:6px 0; border-bottom:1px dashed rgba(41,230,255,.15); color:#d8f6ff;}
.rule b{color:#7ff3ff;} .rule a{color:#29e6ff; text-decoration:none;}
.mismatch{padding:8px 10px; margin:6px 0; font-size:13px; border:1px solid #ffb347; color:#ffe6c2;}
.verified{display:inline-block; padding:3px 10px; font-size:11px; letter-spacing:.2em;
  border:1px solid #39ff9f; color:#39ff9f;}
.fp-k{font-size:10px; letter-spacing:.2em; color:#5f8ea3; margin-top:6px;}
.fp-v{font-size:12.5px; color:#e9fbff; white-space:pre-wrap;}
</style>
"""


def render_stage_map(report: dict) -> str:
    if not report:
        return ""
    cur = STAGE_INDEX.get(report["stage"], 0)
    steps = ""
    for i, s in enumerate(STAGES):
        cls = "now" if i == cur else ("done" if i < cur else "")
        steps += f'<div class="step {cls}">{esc(s["label"]).upper()}</div>'
    alerts = "".join(f'<div class="alert {esc(a["level"])}">{esc(a["text"])}</div>'
                     for a in report.get("alerts", []))
    mism = "".join(f'<div class="mismatch">CHECK: {esc(m)}</div>' for m in report.get("mismatches", []))
    badge = ('<span class="verified">INTAKE VERIFIED BY SURVEY</span>' if report.get("verified")
             else '<span class="chip warn">NEEDS CLARIFICATION</span>' if report.get("mismatches") else "")
    rules = "".join(
        f'<div class="rule"><b>{esc(RULES[r]["title"])}</b> · {esc(RULES[r]["cite"])}'
        f'<br>{esc(RULES[r]["plain"])} <a href="{esc(RULES[r]["url"])}" target="_blank">source</a></div>'
        for r in report.get("rules", []) if r in RULES)
    forms = "".join(
        f'<div class="rule"><b>{esc(f)}</b> {esc(FORMS[f]["name"])}<br>Filed with: {esc(FORMS[f]["where"])} '
        f'<a href="{esc(FORMS[f]["url"])}" target="_blank">official page</a></div>'
        for f in report.get("forms", []) if f in FORMS)
    looks = "".join(f'<div class="rule"><a href="{esc(l["url"])}" target="_blank">{esc(l["name"])}</a>'
                    f'<br>{esc(l["note"])}</div>' for l in LOOKUPS)
    conc = ""
    for k in report.get("concerns", []):
        c = CONCERNS.get(k)
        if not c:
            continue
        links = "".join(f'<div class="rule"><a href="{esc(u)}" target="_blank">{esc(n)}</a> '
                        f'<span style="color:#5f8ea3">{esc(u.split("/")[2])}</span></div>' for n, u in c["links"])
        note = f'<div class="log">{esc(c["note"])}</div>' if c.get("note") else ""
        conc += (f'<div class="panel"><div class="ptitle">{esc(c["label"]).upper()}</div>'
                 f'<div style="font-size:13px;color:#d8f6ff;margin-bottom:6px">{esc(c["plain"])}</div>{links}{note}</div>')
    conc_block = (f'<div class="ptitle" style="margin-top:12px">YOUR STATUS CONCERNS // OFFICIAL .GOV TOOLS</div>'
                  f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px">{conc}</div>'
                  if conc else "")
    return f"""{CSS}
<div class="panel"><div class="ptitle">IMMIGRATION PROCEDURE // WHERE YOU ARE {badge}</div>
<div class="stepper">{steps}</div>
<div style="font-size:13px;color:#d8f6ff;margin-bottom:6px">{esc(STAGES[cur]["desc"])}</div>
{mism}{alerts}</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:10px">
<div class="panel"><div class="ptitle">RULES &amp; REGULATIONS</div>{rules or '<div class="log">Shown after the survey.</div>'}</div>
<div class="panel"><div class="ptitle">THE APPLICATION // FORMS</div>{forms}</div>
<div class="panel"><div class="ptitle">CHECK STATUS &amp; SAFE HELP</div>{looks}</div>
</div>
{conc_block}
<div class="disclaimer">Legal information only, not legal advice. Rules are cited for reference and
are re checked against official .gov sources during research. Confirm with a licensed immigration
attorney, legal aid, or a DOJ accredited representative.</div>"""


def render_flashpoint_panel(status: dict, lens: dict | None, calibration: str,
                            descriptor: str | None, log: list[str]) -> str:
    mode = ('<span class="chip ok">LIVE · x402 USDC</span>' if status.get("live")
            else '<span class="chip warn">OFFLINE · CACHE</span>')
    addr = status.get("address") or "no wallet in .env"
    body = (f'<div class="fp-k">WALLET</div><div class="fp-v">{esc(addr)} · spent ${status.get("spent", 0):.2f}</div>'
            f'<div class="fp-k">SENT TO FLASHPOINT (ANONYMOUS)</div>'
            f'<div class="fp-v">{esc(descriptor or "nothing yet")}</div>')
    if lens:
        body += f'<div class="fp-k">COMMUNITY LENS · {esc(lens.get("source", "")).upper()}</div>' \
                f'<div class="fp-v">{esc(lens.get("summary", ""))}</div>'
    if calibration:
        body += f'<div class="fp-k">SURVEY CALIBRATION NOTES</div><div class="fp-v">{esc(calibration[:700])}</div>'
    if log:
        body += '<div class="fp-k">CALLS</div><div class="log">' + "<br>".join(esc(x) for x in log[-5:]) + "</div>"
    return f'{CSS}<div class="panel"><div class="ptitle">FLASHPOINT.AI // COMMUNITY LENS {mode}</div>{body}</div>'
