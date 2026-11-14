"""JARVIS Immigration: voice first immigration legal information (Streamlit).

English is the main language; Spanish, Georgian and Egyptian Arabic are the
test languages. Flashpoint.AI supplies the community lens and the calibrated
on the spot procedural survey that verifies the voice intake.

Run:  streamlit run app.py
"""
from __future__ import annotations

import html
import math
import os
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass
# Hackathon Claude key (from the organizers) takes priority today; personal key is the fallback.
if os.getenv("ANTHROPIC_API_KEY_HACKATHON"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY_HACKATHON"]

from core.authority import TIER_LABELS
from core.classifier import LAW_AREAS
from core.deadlines import compute_deadline, find_first_step
from core.intake import (SLOT_LABELS, CaseFile, is_advice_seeking,
                         ADVICE_REFUSAL, list_known_entities)
from core.orchestrator import Orchestrator, MODEL, GUARDRAIL
from core import voice
from core.lawyer import claude_legal_chat, generate_irac_memo, memo_to_pdf
from core.procedure import select_procedure, locate_stages
from ui.procedure_map import render_procedure_map
from ui.agent_view import render_agent_cards, render_validator_summary
from ui.immigration_view import render_stage_map, render_flashpoint_panel, CSS as IMM_CSS
from core import dialect
from core.languages import LANGUAGES, TEST_LANGUAGES, lang as lang_spec
from core.flashpoint import FlashpointClient
from core.immigration import SURVEY, score_survey, GAP_SURVEY
from core import workflow as wfm
from ui.workflow_view import render_tracker, render_events
import json as _json

try:
    import anthropic as _anthropic_mod
except ImportError:
    _anthropic_mod = None

st.set_page_config(page_title="JARVIS Immigration", page_icon="⚖️", layout="wide",
                   initial_sidebar_state="collapsed")

USER = os.getenv("JARVIS_USER", "GUEST")

# ------------------------------------------------------------------ state
if "case" not in st.session_state:
    st.session_state.case = CaseFile()
    st.session_state.orch = Orchestrator()
    st.session_state.booted = False
    st.session_state.consent_given = False
    st.session_state.voice_mode = False
    st.session_state.voice_lang = "English"
    st.session_state.voice_messages = []        # chat history for Claude follow-up
    st.session_state.lawyer_mode = False
    st.session_state.lawyer_messages = []       # Claude Legal chat history
    st.session_state.lawyer_sources = []        # accumulated sources from chat
    st.session_state.lawyer_memo = None         # generated IRAC memo text
    st.session_state.fp = FlashpointClient()
    st.session_state.fp_lens = None
    st.session_state.survey_open = False
case: CaseFile = st.session_state.case
orch: Orchestrator = st.session_state.orch
fp: FlashpointClient = st.session_state.setdefault("fp", FlashpointClient())

if not case.workflow:
    case.workflow = wfm.default_state()
wf: dict = case.workflow

_CAL_FILE = Path(__file__).parent / "data" / "flashpoint_calibration.json"


def _gap_map(language: str | None = None) -> list:
    try:
        return _json.loads(_CAL_FILE.read_text()).get(language or case.language, {}).get("gap_map", []) or []
    except Exception:
        return []


def _calibration(language: str | None = None) -> str:
    """Flashpoint survey calibration notes for this language community (prebuilt)."""
    language = language or case.language
    try:
        return _json.loads(_CAL_FILE.read_text()).get(language, {}).get("notes", "")
    except Exception:
        return ""


def _local(text_en: str) -> str:
    """English text rendered in the person's language and dialect."""
    if case.language == "English":
        return text_en
    return dialect.render_question(text_en, case.language, case.dialect, _calibration())


def _ask(text_en: str) -> None:
    """Jarvis says something: English is canonical, the person sees their language."""
    case.transcript.append({"role": "jarvis", "text": text_en, "text_local": _local(text_en),
                            "lang": case.language})

# ------------------------------------------------------------------ theme
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Share+Tech+Mono&display=swap');
:root{
  --bg:#01060c; --panel:rgba(6,28,44,.55); --line:rgba(41,230,255,.28);
  --cyan:#29e6ff; --cyan2:#7ff3ff; --dim:#5f8ea3; --warn:#ffb347; --bad:#ff4d6d; --ok:#3dffb5;
}
html, body, [data-testid="stAppViewContainer"], .stApp{
  background:
    radial-gradient(ellipse at 50% 38%, rgba(41,230,255,.16), transparent 55%),
    linear-gradient(rgba(41,230,255,.05) 1px, transparent 1px) 0 0/34px 34px,
    linear-gradient(90deg, rgba(41,230,255,.05) 1px, transparent 1px) 0 0/34px 34px,
    var(--bg) !important;
  color:#cfefff; font-family:'Share Tech Mono', monospace;
}
[data-testid="stHeader"]{background:transparent;}
.block-container{padding-top:1.2rem; max-width:1500px; padding-bottom:100px;}
h1,h2,h3,h4{font-family:'Orbitron',sans-serif !important; color:var(--cyan) !important; letter-spacing:.12em;}
p, li, span, label, div{font-family:'Share Tech Mono', monospace;}

.topbar{display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;
  border:1px solid var(--line); background:var(--panel); padding:10px 18px; border-radius:4px;
  box-shadow:0 0 24px rgba(41,230,255,.12) inset;}
.brand{font-family:'Orbitron'; font-weight:900; font-size:22px; color:var(--cyan); letter-spacing:.3em;
  text-shadow:0 0 12px rgba(41,230,255,.8);}
.brand small{display:block; font-size:10px; letter-spacing:.35em; color:var(--dim); font-weight:500;}
.chip{display:inline-block; border:1px solid var(--line); padding:3px 10px; margin:2px; font-size:11px;
  letter-spacing:.12em; color:var(--cyan2); background:rgba(41,230,255,.06); border-radius:2px;}
.chip.ok{color:var(--ok); border-color:rgba(61,255,181,.4);}
.chip.warn{color:var(--warn); border-color:rgba(255,179,71,.45);}
.chip.bad{color:var(--bad); border-color:rgba(255,77,109,.45);}

.panel{border:1px solid var(--line); background:var(--panel); padding:14px 16px; margin-bottom:14px;
  position:relative; border-radius:3px; box-shadow:0 0 30px rgba(41,230,255,.07) inset;}
.panel:before,.panel:after{content:""; position:absolute; width:14px; height:14px; border-color:var(--cyan);}
.panel:before{top:-1px; left:-1px; border-top:2px solid; border-left:2px solid;}
.panel:after{bottom:-1px; right:-1px; border-bottom:2px solid; border-right:2px solid;}
.ptitle{font-family:'Orbitron'; font-size:11px; letter-spacing:.3em; color:var(--cyan); margin-bottom:10px;
  display:flex; justify-content:space-between;}
.ptitle span{color:var(--dim);}
.question{font-size:17px; line-height:1.45; color:#e9fbff; text-shadow:0 0 8px rgba(41,230,255,.35);}
.fact{display:grid; grid-template-columns:110px 1fr; gap:8px; padding:5px 0; border-bottom:1px dashed rgba(41,230,255,.12); font-size:13px;}
.fact b{color:var(--cyan); font-weight:400; letter-spacing:.08em;}
.bar{height:6px; background:rgba(41,230,255,.12); margin:6px 0 2px; overflow:hidden;}
.bar i{display:block; height:100%; background:linear-gradient(90deg,var(--cyan),var(--cyan2)); box-shadow:0 0 10px var(--cyan);}
.src{padding:8px 0; border-bottom:1px dashed rgba(41,230,255,.12); font-size:12.5px;}
.src a{color:#dff8ff; text-decoration:none;} .src a:hover{color:var(--cyan);}
.tier{font-size:10px; padding:1px 6px; margin-right:6px; letter-spacing:.1em; border:1px solid;}
.t1{color:var(--ok); border-color:var(--ok);} .t2{color:var(--cyan); border-color:var(--cyan);}
.t3{color:var(--warn); border-color:var(--warn);} .t4,.t5{color:var(--bad); border-color:var(--bad);}
.log{font-size:12px; color:var(--dim); max-height:190px; overflow:auto;}
.log b{color:var(--cyan2); font-weight:400;}
.finding{font-size:13.5px; line-height:1.5; color:#d8f6ff; white-space:pre-wrap;}
.disclaimer{font-size:11px; color:var(--warn); letter-spacing:.06em; text-align:center; margin-top:6px;}

.reactor-wrap{display:flex; flex-direction:column; align-items:center; justify-content:center; padding-top:8px;}
.reactor{width:min(420px,88vw); aspect-ratio:1; position:relative;}
.reactor svg{width:100%; height:100%; overflow:visible;}
.spin{transform-origin:200px 200px; animation:spin 22s linear infinite;}
.spin.r{animation-direction:reverse; animation-duration:14s;}
.spin.f{animation-duration:7s;}
.pulse{animation:pulse 2.4s ease-in-out infinite; transform-origin:200px 200px;}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:.75; transform:scale(1)}50%{opacity:1; transform:scale(1.04)}}
.status{font-family:'Orbitron'; letter-spacing:.35em; font-size:12px; color:var(--cyan); margin-top:6px; text-align:center;}
.areas{display:flex; flex-wrap:wrap; justify-content:center; gap:6px; margin:10px 0 16px;}
.area{border:1px solid var(--line); padding:8px 12px; text-align:center; min-width:120px; background:rgba(41,230,255,.05);}
.area .k{font-family:'Orbitron'; font-size:20px; color:var(--cyan); text-shadow:0 0 10px var(--cyan);}
.area .n{font-size:11px; letter-spacing:.08em;}
.tl{border-left:2px solid var(--line); margin-left:6px; padding-left:12px; font-size:12.5px;}
.tl div{margin:6px 0; position:relative;} .tl div:before{content:""; position:absolute; left:-17px; top:5px; width:8px; height:8px; background:var(--cyan); box-shadow:0 0 8px var(--cyan);}

.deadline-big{font-family:'Orbitron'; font-size:28px; color:var(--warn); text-shadow:0 0 14px rgba(255,179,71,.6); letter-spacing:.08em; margin:8px 0;}
.deadline-big.expired{color:var(--bad); text-shadow:0 0 14px rgba(255,77,109,.6);}
.deadline-days{font-family:'Orbitron'; font-size:14px; letter-spacing:.2em; margin-bottom:10px;}
.step-item{padding:8px 0; border-bottom:1px dashed rgba(41,230,255,.12); font-size:13.5px; line-height:1.5; color:#d8f6ff;}
.step-num{color:var(--cyan); font-family:'Orbitron'; font-size:13px; margin-right:8px;}
.unverified{display:inline-block; border:1px solid var(--warn); padding:2px 8px; font-size:10px;
  letter-spacing:.15em; color:var(--warn); background:rgba(255,179,71,.08); margin:4px 0;}
.entity-confirm{border:1px solid var(--warn); padding:10px 14px; margin:8px 0; background:rgba(255,179,71,.06);}

/* Streamlit widgets in HUD style */
.stButton>button{background:rgba(41,230,255,.08) !important; color:var(--cyan) !important; border:1px solid var(--cyan) !important;
  font-family:'Orbitron' !important; letter-spacing:.2em; font-size:11px !important; border-radius:2px !important; width:100%;}
.stButton>button:hover{background:rgba(41,230,255,.2) !important; box-shadow:0 0 16px rgba(41,230,255,.5);}
[data-testid="stChatInput"]{background:rgba(6,28,44,.9) !important; border:1px solid var(--cyan) !important; border-radius:3px !important;}
[data-testid="stChatInput"] > div, [data-testid="stChatInput"] div{background:transparent !important;}
[data-testid="stChatInput"] textarea::placeholder{color:#5f8ea3 !important;}
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu{display:none !important;}
[data-testid="stChatInput"] textarea{color:#e9fbff !important; font-family:'Share Tech Mono' !important;}
[data-testid="stBottom"] > div{background:transparent !important;}
details{border:1px solid var(--line) !important; background:var(--panel) !important;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def reactor_svg(active_agents: int, prog: float) -> str:
    ticks = "".join(
        f'<line x1="200" y1="18" x2="200" y2="{30 if i % 5 else 40}" stroke="#29e6ff" stroke-width="{1 if i % 5 else 2}" '
        f'opacity="{.45 if i % 5 else .9}" transform="rotate({i * 6} 200 200)"/>'
        for i in range(60)
    )
    segs = "".join(
        f'<path d="M200 70 A130 130 0 0 1 {200 + 130 * math.sin(0.42):.1f} {200 - 130 * math.cos(0.42):.1f}" '
        f'stroke="#29e6ff" stroke-width="10" fill="none" opacity=".55" transform="rotate({i * 30} 200 200)"/>'
        for i in range(12)
    )
    arc = 2 * 3.14159 * 168
    return f"""
<svg viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="core" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff"/><stop offset="35%" stop-color="#bff9ff"/>
      <stop offset="70%" stop-color="#29e6ff" stop-opacity=".55"/><stop offset="100%" stop-color="#29e6ff" stop-opacity="0"/>
    </radialGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <g class="spin" filter="url(#glow)">{ticks}</g>
  <circle cx="200" cy="200" r="168" stroke="rgba(41,230,255,.15)" stroke-width="6" fill="none"/>
  <circle cx="200" cy="200" r="168" stroke="#29e6ff" stroke-width="6" fill="none" stroke-linecap="round"
    stroke-dasharray="{arc * prog:.1f} {arc:.1f}" transform="rotate(-90 200 200)" filter="url(#glow)"/>
  <g class="spin r">{segs}</g>
  <g class="spin f"><circle cx="200" cy="200" r="104" stroke="#29e6ff" stroke-width="2" fill="none"
     stroke-dasharray="4 10" opacity=".8"/></g>
  <circle cx="200" cy="200" r="92" stroke="#7ff3ff" stroke-width="1.5" fill="rgba(41,230,255,.06)"/>
  <g class="pulse" filter="url(#glow)">
    <polygon points="200,128 262,236 138,236" fill="rgba(41,230,255,.12)" stroke="#bff9ff" stroke-width="3"/>
    <polygon points="200,150 243,224 157,224" fill="none" stroke="#29e6ff" stroke-width="2" opacity=".8"/>
    <circle cx="200" cy="200" r="46" fill="url(#core)"/>
  </g>
</svg>"""


# ------------------------------------------------------------------ consent gate
if not st.session_state.consent_given:
    st.markdown("""
<div style="max-width:720px; margin:80px auto; text-align:center;">
  <div style="font-family:'Orbitron',sans-serif; font-size:28px; letter-spacing:.3em;
    color:#29e6ff; text-shadow:0 0 20px rgba(41,230,255,.7); margin-bottom:30px;">
    J.A.R.V.I.S.</div>
  <div style="font-size:20px; line-height:2; color:#e9fbff; text-shadow:0 0 6px rgba(41,230,255,.3);">
    This is an <b style="color:#29e6ff;">educational prototype</b> for general legal information only.<br>
    It is <b style="color:#ff4d6d;">not</b> legal advice and does not replace a licensed attorney.<br>
    JARVIS never asks for an A-number, SSN, or passport number, and never shares your story.<br>
    Only an anonymous community description (language + neighborhood) is sent to Flashpoint.AI.<br>
    Any deadline shown is an estimate — confirm with a lawyer or legal aid.<br>
    Do not rely on this tool for a real claim.<br>
    <span style="color:#ffb347;">By continuing you acknowledge this disclaimer.</span>
  </div>
</div>""", unsafe_allow_html=True)
    if st.button("I UNDERSTAND — BEGIN INTAKE"):
        st.session_state.consent_given = True
        st.rerun()
    st.stop()


# ================================================================== VOICE MODE (overlay on dashboard)
def _jarvis_speak(text: str, already_local: bool = False) -> None:
    """Speak text via ElevenLabs and auto-play in browser.

    If a non-English language is selected, translates before speaking so the
    ElevenLabs model renders the correct language with the British voice.
    """
    lang = case.language
    if lang != "English" and not already_local:
        text = _local(text)
    audio_b64 = voice.speak_b64(text, language=lang)
    if audio_b64:
        st.markdown(voice.autoplay_audio_html(audio_b64), unsafe_allow_html=True)


def _claude_chat(messages: list[dict], system: str = "") -> str:
    """Send messages to Claude and return the assistant response text."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or _anthropic_mod is None:
        return "Claude API is not available. Please set ANTHROPIC_API_KEY."
    client = _anthropic_mod.Anthropic(api_key=key)
    resp = client.messages.create(
        model=MODEL, max_tokens=2000, system=system or GUARDRAIL,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _build_findings_summary() -> str:
    """Build a text summary of research findings for the voice agent."""
    if not orch.findings:
        return "No research findings available yet."
    parts = []
    for f in orch.findings:
        src_names = ", ".join(s.title or s.domain for s in f.sources[:5])
        parts.append(f"{f.title}: {f.body}\nSources: {src_names}")
    return "\n\n".join(parts)


def _build_action_items() -> list[str]:
    """Generate action items from the case file and findings."""
    area = case.primary_area or ""
    resp = case.resolved_entity or ""
    first_step = find_first_step(area, resp) if area else None
    items = []
    if first_step:
        for step in first_step.get("plain_language_steps", []):
            items.append(step)
        if case.when_iso:
            dl = compute_deadline(case.when_iso, first_step["deadline_rule"])
            if not dl.is_expired:
                items.insert(0, f"DEADLINE: {dl.deadline_date.strftime('%B %d, %Y')} ({dl.days_remaining} days remaining) - {dl.label}")
            else:
                items.insert(0, f"DEADLINE EXPIRED: {dl.deadline_date.strftime('%B %d, %Y')} - consult an attorney immediately")
    if not items:
        items = [
            "Consult with a licensed attorney in your jurisdiction",
            "Gather and preserve all evidence and documents",
            "Note any upcoming deadlines or court dates",
            "Contact your local legal aid organization for free help",
        ]
    return items


def _voice_auto_listen_html(lang_code: str) -> str:
    """Continuous hands-free STT. Auto-starts, auto-submits to Streamlit chat input."""
    return f"""
<div id="jarvis-stt" style="text-align:center; padding:4px 0;">
  <div id="stt-indicator" style="display:inline-flex; align-items:center; gap:8px;
    border:1px solid rgba(41,230,255,.4); padding:6px 16px; border-radius:3px;
    background:rgba(41,230,255,.06);">
    <div id="stt-dot" style="width:10px; height:10px; border-radius:50%;
      background:#3dffb5; box-shadow:0 0 8px #3dffb5;
      animation: pulse-dot 1.5s ease-in-out infinite;"></div>
    <span id="stt-label" style="font-family:'Orbitron',sans-serif; font-size:11px;
      letter-spacing:.25em; color:#29e6ff;">LISTENING</span>
  </div>
  <div id="stt-live" style="font-size:13px; color:#7ff3ff; margin-top:6px;
    min-height:20px; font-family:'Share Tech Mono',monospace;"></div>
</div>
<style>
@keyframes pulse-dot {{
  0%,100% {{ opacity:.6; transform:scale(1); }}
  50% {{ opacity:1; transform:scale(1.3); }}
}}
</style>
<script>
(function() {{
  const LANG = '{lang_code}';
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {{
    document.getElementById('stt-label').textContent = 'BROWSER NOT SUPPORTED';
    document.getElementById('stt-dot').style.background = '#ff4d6d';
    return;
  }}

  let recognition = null;
  let restartTimer = null;

  function submitText(text) {{
    // Find Streamlit's chat textarea and submit
    const frame = window.parent.document;
    const ta = frame.querySelector('textarea[data-testid="stChatInputTextArea"]');
    if (!ta) return;
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    nativeSetter.call(ta, text);
    ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
    // Simulate Enter key to submit
    setTimeout(() => {{
      ta.dispatchEvent(new KeyboardEvent('keydown', {{
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
      }}));
    }}, 100);
  }}

  function startListening() {{
    if (recognition) try {{ recognition.abort(); }} catch(e) {{}}
    recognition = new SpeechRecognition();
    recognition.lang = LANG;
    recognition.interimResults = true;
    recognition.continuous = true;
    recognition.maxAlternatives = 1;

    const dot = document.getElementById('stt-dot');
    const label = document.getElementById('stt-label');
    const live = document.getElementById('stt-live');

    dot.style.background = '#3dffb5';
    dot.style.boxShadow = '0 0 8px #3dffb5';
    label.textContent = 'LISTENING';

    let finalTranscript = '';
    let silenceTimer = null;

    recognition.onresult = function(e) {{
      let interim = '';
      finalTranscript = '';
      for (let i = 0; i < e.results.length; i++) {{
        if (e.results[i].isFinal) {{
          finalTranscript += e.results[i][0].transcript;
        }} else {{
          interim += e.results[i][0].transcript;
        }}
      }}
      live.textContent = finalTranscript || interim;
      dot.style.background = '#ffb347';
      dot.style.boxShadow = '0 0 8px #ffb347';
      label.textContent = 'HEARING';

      // After final result + 1.5s silence, auto-submit
      if (finalTranscript) {{
        clearTimeout(silenceTimer);
        silenceTimer = setTimeout(() => {{
          if (finalTranscript.trim()) {{
            label.textContent = 'SUBMITTING';
            submitText(finalTranscript.trim());
            live.textContent = '';
            finalTranscript = '';
          }}
        }}, 1500);
      }}
    }};

    recognition.onend = function() {{
      // Auto-restart after a brief pause
      dot.style.background = '#5f8ea3';
      label.textContent = 'RESTARTING';
      clearTimeout(restartTimer);
      restartTimer = setTimeout(startListening, 800);
    }};

    recognition.onerror = function(e) {{
      if (e.error === 'no-speech' || e.error === 'aborted') {{
        // Normal — just restart
        return;
      }}
      dot.style.background = '#ff4d6d';
      label.textContent = 'ERROR: ' + e.error.toUpperCase();
      clearTimeout(restartTimer);
      restartTimer = setTimeout(startListening, 2000);
    }};

    recognition.start();
  }}

  // Start immediately
  startListening();
}})();
</script>"""


# ================================================================== LAWYER MODE UI
LAWYER_CSS = """
<style>
.lawyer-panel{border:1px solid rgba(255,215,0,.35); background:rgba(20,15,5,.6); padding:16px 18px;
  margin-bottom:14px; position:relative; border-radius:3px;
  box-shadow:0 0 30px rgba(255,215,0,.06) inset;}
.lawyer-panel:before,.lawyer-panel:after{content:""; position:absolute; width:14px; height:14px; border-color:#ffd700;}
.lawyer-panel:before{top:-1px; left:-1px; border-top:2px solid; border-left:2px solid;}
.lawyer-panel:after{bottom:-1px; right:-1px; border-bottom:2px solid; border-right:2px solid;}
.lawyer-title{font-family:'Orbitron',sans-serif; font-size:11px; letter-spacing:.3em; color:#ffd700; margin-bottom:10px;}
.lawyer-body{font-size:13.5px; line-height:1.6; color:#f5e6c8; white-space:pre-wrap;}
.lawyer-src{font-size:11px; padding:4px 0; border-bottom:1px dashed rgba(255,215,0,.15);}
.lawyer-src a{color:#ffd700; text-decoration:none;} .lawyer-src a:hover{text-decoration:underline;}
.memo-text{font-family:'Times New Roman',Georgia,serif; font-size:14px; line-height:1.7; color:#f0e8d8;
  white-space:pre-wrap; background:rgba(30,25,15,.5); padding:20px; border:1px solid rgba(255,215,0,.2);}
</style>
"""


def _lawyer_mode_ui():
    """Full Lawyer Mode interface: Claude Legal chat + IRAC memo + PDF download."""
    st.markdown(LAWYER_CSS, unsafe_allow_html=True)

    # Handoff consent screen (shown once)
    if not st.session_state.get("lawyer_consent_given"):
        st.markdown("""
<div class="lawyer-panel" style="max-width:680px; margin:40px auto; text-align:center;">
<div class="lawyer-title">LAWYER MODE — HANDOFF CONSENT</div>
<div style="font-size:14px; color:#f5e6c8; line-height:1.7;">
This will transfer the case facts, research findings, and sources<br>
from the JARVIS intake into Lawyer Mode for attorney review.<br><br>
This is an <b style="color:#ffd700;">educational demo</b>. No attorney-client<br>
relationship is created by using this tool.<br><br>
<span style="color:#ffb347;">By continuing you consent to this transfer.</span>
</div>
</div>""", unsafe_allow_html=True)
        if st.button("I CONSENT — ENTER LAWYER MODE"):
            st.session_state.lawyer_consent_given = True
            # Log consent in case
            case.transcript.append({"role": "system",
                "text": f"Lawyer Mode handoff consent given at {time.strftime('%H:%M:%S')}"})
            case.save()
            st.rerun()
        if st.button("CANCEL — BACK TO JARVIS", key="lawyer_cancel"):
            st.session_state.lawyer_mode = False
            st.rerun()
        return

    # Top bar
    st.markdown(f"""
<div class="topbar" style="border-color:rgba(255,215,0,.35);">
<div class="brand" style="color:#ffd700; text-shadow:0 0 12px rgba(255,215,0,.6);">
LAWYER MODE<small>CLAUDE LEGAL · IRAC MEMORANDUM</small></div>
<div><span class="chip" style="color:#ffd700; border-color:#ffd700;">EDUCATIONAL DEMO</span>
<span class="chip">CASE {esc(case.created)}</span>
<span class="chip">{time.strftime('%a %b %d  %H:%M')}</span></div>
</div>""", unsafe_allow_html=True)
    st.write("")

    # Controls
    lc1, lc2, lc3 = st.columns([1, 1, 1])
    with lc1:
        if st.button("BACK TO JARVIS"):
            st.session_state.lawyer_mode = False
            st.rerun()
    with lc2:
        _gen_disabled = not orch.findings and not st.session_state.lawyer_messages
        if st.button("GENERATE IRAC MEMO", disabled=_gen_disabled, key="gen_memo"):
            st.session_state._generate_memo = True
            st.rerun()
    with lc3:
        if st.session_state.lawyer_memo:
            if st.button("DOWNLOAD PDF", key="dl_pdf"):
                st.session_state._download_pdf = True

    # Case summary panel
    if case.facts:
        st.markdown(f"""
        <div class="lawyer-panel">
          <div class="lawyer-title">CASE SUMMARY — TRANSFERRED FROM JARVIS</div>
          <div class="lawyer-body">{esc(case.summary_text())}</div>
        </div>""", unsafe_allow_html=True)

    # Research findings panel
    if orch.findings:
        for f in orch.findings:
            src_html = ""
            for s in f.sources[:6]:
                src_html += (f'<div class="lawyer-src">'
                             f'<a href="{esc(s.url)}" target="_blank">{esc(s.title or s.domain)}</a>'
                             f' <span style="color:#8a7a5a;">T{s.tier} · {s.domain}</span></div>')
            st.markdown(f"""
            <div class="lawyer-panel">
              <div class="lawyer-title">{esc(f.title).upper()}</div>
              <div class="lawyer-body">{esc(f.body)}</div>
              {src_html}
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # Claude Legal Chat
    st.markdown("""
    <div class="lawyer-panel">
      <div class="lawyer-title">CLAUDE LEGAL — RESEARCH CHAT</div>
      <div style="font-size:12px; color:#c4b48a;">
        Discuss prior cases, ask for additional research, or refine your analysis.
        Claude Legal has web search access for case law and statutes.
        Chat history feeds into the IRAC memo when generated.
      </div>
    </div>""", unsafe_allow_html=True)

    # Chat history
    for m in st.session_state.lawyer_messages:
        who = "ATTORNEY" if m["role"] == "user" else "CLAUDE LEGAL"
        color = "#f0e8d8" if m["role"] == "user" else "#ffd700"
        st.markdown(f"""
        <div class="lawyer-panel" style="margin-bottom:8px;">
          <div style="font-size:10px; letter-spacing:.2em; color:{color};">{who}</div>
          <div class="lawyer-body" style="margin-top:4px;">{esc(m["content"])}</div>
        </div>""", unsafe_allow_html=True)

    # Chat input
    _query = st.chat_input("Research query for Claude Legal...", key="lawyer_chat")
    if _query:
        st.session_state.lawyer_messages.append({"role": "user", "content": _query})

        # Build context-aware messages
        _sys_ctx = (
            f"Case facts:\n{case.summary_text()}\n\n"
            + (f"Research findings:\n{_build_findings_summary()}\n\n" if orch.findings else "")
            + "The attorney may ask about prior cases, legal strategy, or request additional research."
        )

        with st.spinner("Claude Legal researching..."):
            _reply, _new_sources = claude_legal_chat(
                st.session_state.lawyer_messages,
                system=f"You are Claude Legal, an AI legal research assistant. You assist attorneys with research, cite sources precisely, and use standard legal citation format.\n\nCONTEXT:\n{_sys_ctx}",
                web_search=True
            )

        st.session_state.lawyer_messages.append({"role": "assistant", "content": _reply})
        st.session_state.lawyer_sources.extend(_new_sources)
        st.rerun()

    # Handle memo generation
    if st.session_state.pop("_generate_memo", False):
        # Gather all sources
        _all_sources = []
        _seen_urls = set()
        for f in orch.findings:
            for s in f.sources:
                if s.url not in _seen_urls:
                    _all_sources.append({"url": s.url, "title": s.title or s.domain})
                    _seen_urls.add(s.url)
        for s in st.session_state.lawyer_sources:
            if s["url"] not in _seen_urls:
                _all_sources.append(s)
                _seen_urls.add(s["url"])

        _findings = [
            {"title": f.title, "body": f.body,
             "sources": [{"url": s.url, "title": s.title} for s in f.sources]}
            for f in orch.findings
        ]

        with st.spinner("Claude Legal generating IRAC memorandum..."):
            memo = generate_irac_memo(
                case_summary=case.summary_text(),
                findings=_findings,
                sources=_all_sources,
                attorney_name=USER,
                prior_discussion=st.session_state.lawyer_messages or None
            )
        st.session_state.lawyer_memo = memo
        case.save()
        if case.folder:
            (case.folder / "irac_memo.txt").write_text(memo)
        # Verify citations via CourtListener
        from sources.courtlistener import verify_memo_citations
        st.session_state.lawyer_citations = verify_memo_citations(memo)
        st.rerun()

    # Display memo if generated
    if st.session_state.lawyer_memo:
        st.markdown("---")
        st.markdown(
            '<div class="lawyer-panel">'
            '<div class="lawyer-title">IRAC MEMORANDUM OF LAW</div>'
            '</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="memo-text">{esc(st.session_state.lawyer_memo)}</div>',
                    unsafe_allow_html=True)

        # Citation verification table
        _cites = st.session_state.get("lawyer_citations", [])
        if _cites:
            st.markdown(
                '<div class="lawyer-panel">'
                '<div class="lawyer-title">CITATION VERIFICATION (CourtListener)</div>',
                unsafe_allow_html=True)
            for c in _cites:
                _v_color = "#3dffb5" if c["verified"] else "#ff4d6d"
                _v_label = "VERIFIED" if c["verified"] else "NOT FOUND"
                _link = f'<a href="{esc(c["url"])}" target="_blank" style="color:#ffd700;">{esc(c["case_name"])}</a>' if c["url"] else ""
                st.markdown(
                    f'<div style="padding:4px 0; border-bottom:1px dashed rgba(255,215,0,.15); font-size:12px;">'
                    f'<span style="color:{_v_color}; font-size:10px; border:1px solid {_v_color}; '
                    f'padding:1px 6px; margin-right:8px; letter-spacing:.1em;">{_v_label}</span>'
                    f'{esc(c["citation"])} {_link}</div>',
                    unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # PDF — generate, save to case folder, and offer download
        _area = case.primary_area or "Legal Matter"
        _pdf = memo_to_pdf(st.session_state.lawyer_memo, f"Memorandum — {_area}")
        _pdf_name = f"IRAC_Memo_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

        # Auto-save to case folder
        if case.folder:
            case.folder.mkdir(parents=True, exist_ok=True)
            _pdf_path = case.folder / _pdf_name
            _pdf_path.write_bytes(_pdf)
            st.markdown(
                f'<div style="font-size:11px; color:#c4b48a; margin:6px 0;">'
                f'Saved to: <code>{_pdf_path}</code></div>',
                unsafe_allow_html=True)

        st.download_button(
            label="DOWNLOAD MEMO AS PDF",
            data=_pdf,
            file_name=_pdf_name,
            mime="application/pdf",
            key="pdf_download"
        )

    st.markdown("""
    <div style="text-align:center; margin-top:20px; font-size:10px; color:#8a7a5a; letter-spacing:.15em;">
      EDUCATIONAL DEMO — NOT LEGAL ADVICE
    </div>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ boot
if not st.session_state.booted:
    orch._log("JARVIS", "systems online" + ("" if orch.online else " in offline demo mode (no API key)"))
    orch._log("JARVIS", "voice module online (ElevenLabs TTS)")
    st.session_state.booted = True
    slot, q = case.next_question()
    case.pending_slot = slot
    _ask("Good day. I'm JARVIS. I help people understand where they are in the immigration "
         "process, the rules that apply, and the official forms. This is information, not legal advice. " + q)

# ------------------------------------------------------------------ input handling
def _handle_answer(raw: str, source: str = "typed", stt: dict | None = None) -> None:
    """One answer from the person, typed or spoken, in any of the four languages."""
    raw = raw.strip()
    if not raw:
        return
    english = raw
    if case.language != "English":
        with st.spinner("JARVIS understanding your words"):
            english, prof = dialect.to_english(raw, case.language)
        rank_c = {"high": 3, "medium": 2, "low": 1}
        if rank_c.get(prof.get("confidence"), 0) >= rank_c.get(case.dialect.get("confidence"), 0):
            case.dialect = {k: v for k, v in prof.items() if k != "english"}
        orch._log("DialectAgent", f"{prof.get('language')} · {prof.get('variety')} ({prof.get('confidence')})")
    case.original_answers.append({"lang": case.language, "source": source, "original": raw,
                                  "english": english, "stt": stt or {}})
    _cmd = english.strip().lower().rstrip(".!")
    _RESEARCH_CMDS = {"run research", "research", "jarvis run research"}
    _FIRST_STEP_CMDS = {"what do i do first", "first step", "what do i do", "next step", "what now"}
    if _cmd in _RESEARCH_CMDS:
        case.transcript.append({"role": "user", "text": english, "text_local": raw})
        if not case.stage_report:
            st.session_state.survey_open = True
            _ask("Before I research, please answer the short check below so I'm sure I understood you.")
        else:
            st.session_state.run_research = True
        return
    if _cmd in _FIRST_STEP_CMDS:
        case.transcript.append({"role": "user", "text": english, "text_local": raw})
        st.session_state.show_first_step_chat = True
        return
    if is_advice_seeking(english):
        case.transcript.append({"role": "user", "text": english, "text_local": raw})
        nxt = case.next_question()
        _ask(ADVICE_REFUSAL + (f"\n\n{nxt[1]}" if nxt else ""))
        return
    with st.spinner("JARVIS processing"):
        orch.extract_facts(case, english)
        case.transcript[-1]["text_local"] = raw
        orch.classify(case)
        nxt = case.next_question()
        if nxt:
            case.pending_slot, q = nxt
            if case.when_raw and not case.when_iso:
                q = (f"I need an exact date (month, day, year) for deadlines. "
                     f"You said \"{case.when_raw}\". What is the specific date?")
                case.pending_slot = "when"
                case.facts.pop("when", None)
            _ask(q)
        else:
            case.pending_slot = None
            st.session_state.survey_open = True
            _ask("Thank you. Now a short check of 8 questions, so I'm sure I understood you correctly "
                 "and know where you are in the immigration process.")
        case.save()


answer = st.chat_input("Type or speak to JARVIS, in English, Spanish, Georgian or Egyptian Arabic")
if answer:
    _handle_answer(answer, "typed")
    st.rerun()

if st.session_state.pop("run_research", False):
    if st.session_state.voice_mode:
        _jarvis_speak("Please wait while I search official legal sources. This will take a moment.")
    with st.spinner("Agents dispatched: StatuteAgent, ContextAgent, ValidatorAgent"):
        orch.research(case)
    case.save()
    # After research, if voice mode, speak a summary
    if st.session_state.voice_mode and orch.findings:
        findings_text = _build_findings_summary()
        action_items = _build_action_items()
        lang = st.session_state.voice_lang
        summary_prompt = (
            f"You are JARVIS, a British-accented AI legal assistant. The user's case:\n"
            f"{case.summary_text()}\n\nResearch findings:\n{findings_text}\n\n"
            f"Action items:\n" + "\n".join(f"- {a}" for a in action_items) + "\n\n"
            f"Summarize conversationally. Be clear, concise, warm. Mention key laws, "
            f"deadlines, action items. Ask if they have follow-up questions. "
            f"Under 200 words. Language: {lang}."
        )
        with st.spinner("JARVIS composing summary..."):
            summary = _claude_chat([{"role": "user", "content": summary_prompt}],
                                   system=GUARDRAIL + "\nSpeak in a warm British manner like JARVIS.")
        st.session_state.voice_summary = summary
        st.session_state.voice_messages = [{"role": "assistant", "content": summary}]

# ------------------------------------------------------------------ "what do I do first" chat handler
if st.session_state.pop("show_first_step_chat", False):
    _rep = case.stage_report
    if _rep:
        _urg = [a["text"] for a in _rep.get("alerts", []) if a["level"] == "urgent"]
        _ask(f"You appear to be at this stage: {_rep['stage_label']}. "
             + (" ".join(_urg) + " " if _urg else "")
             + f"The forms usually involved here are {', '.join(_rep.get('forms', []))}. "
             "For a decision about your own case, contact ActionNYC (call 311) or a licensed immigration attorney.")
    else:
        _ask("First, finish the questions and the short check, so I know where you are in the process.")

# ------------------------------------------------------------------ top bar
mode = '<span class="chip ok">ONLINE</span>' if orch.online else '<span class="chip warn">OFFLINE DEMO</span>'
_voice_chip = (f'<span class="chip ok">VOICE: ON · {esc(st.session_state.voice_lang).upper()}</span>'
               if st.session_state.voice_mode
               else '<span class="chip">VOICE: OFF</span>')
_tb_left, _tb_right = st.columns([4, 1])
with _tb_left:
    st.markdown(f"""
    <div class="topbar">
      <div class="brand">J.A.R.V.I.S.<small>IMMIGRATION · VOICE INTAKE · FLASHPOINT VERIFIED</small></div>
      <div>{mode}<span class="chip">USER: {esc(USER).upper()}</span><span class="chip">CASE {esc(case.created)}</span>
      <span class="chip">{time.strftime('%a %b %d  %H:%M')}</span>{_voice_chip}
      <span class="chip ok">LANGUAGE: {esc(case.language).upper()}</span></div>
    </div>""", unsafe_allow_html=True)
with _tb_right:
    st.markdown("""<style>
    div[data-testid="stColumn"]:last-child .stButton>button#lawyer-btn {
      background: linear-gradient(135deg, rgba(255,215,0,.15), rgba(255,179,71,.1)) !important;
      border: 2px solid #ffd700 !important; color: #ffd700 !important;
      font-size: 11px !important; padding: 10px 16px !important;
      box-shadow: 0 0 18px rgba(255,215,0,.3) !important;
      text-shadow: 0 0 6px rgba(255,215,0,.6);
      letter-spacing: .15em !important; margin-top: 8px;
    }
    div[data-testid="stColumn"]:last-child .stButton>button#lawyer-btn:hover {
      box-shadow: 0 0 28px rgba(255,215,0,.6) !important;
    }
    </style>""", unsafe_allow_html=True)
    _langs = list(LANGUAGES)
    _pick = st.selectbox("Language", _langs, index=_langs.index(case.language),
                         format_func=lambda n: f"{n} · {LANGUAGES[n]['native']}" if n != "English" else n,
                         key="lang_pick", label_visibility="collapsed")
    if _pick != case.language:
        case.language = _pick
        st.session_state.voice_lang = _pick
        case.dialect = {}
        orch._log("JARVIS", f"language set to {_pick}")
        # re render the current question in the new language
        for m in reversed(case.transcript):
            if m["role"] == "jarvis":
                m["text_local"] = _local(m["text"]); m["lang"] = _pick
                break
        st.rerun()
    if st.button("LAWYER MODE", key="lawyer-btn"):
        st.session_state.lawyer_mode = True
        st.rerun()
st.write("")

st.markdown(render_tracker(case, wf), unsafe_allow_html=True)

# ================================================================== LAWYER MODE
if st.session_state.lawyer_mode:
    _lawyer_mode_ui()
    st.stop()

left, center, right = st.columns([1.15, 1.3, 1.15], gap="medium")

# ------------------------------------------------------------------ LEFT: intake
with left:
    _lm = next((m for m in reversed(case.transcript) if m["role"] == "jarvis"), {"text": ""})
    last_q = _lm.get("text_local") or _lm["text"]
    _rtl = ' dir="rtl" style="text-align:right"' if lang_spec(case.language)["rtl"] else ""
    _en_line = (f'<div class="log" style="margin-top:6px">EN · {esc(_lm["text"])}</div>'
                if case.language != "English" and last_q != _lm["text"] else "")
    prog = case.progress()
    st.markdown(f"""
<div class="panel"><div class="ptitle">INTAKE // CURRENT QUERY <span>{prog * 100:.0f}%</span></div>
<div class="question"{_rtl}>{esc(last_q)}</div>{_en_line}
<div class="bar"><i style="width:{prog * 100:.0f}%"></i></div></div>""", unsafe_allow_html=True)

    # ---- voice transcription (ElevenLabs Scribe, any of the four languages)
    _rec = st.audio_input(f"Answer by voice ({case.language})", key=f"rec_{len(case.transcript)}")
    if _rec is not None:
        with st.spinner("Transcribing"):
            _tr = dialect.transcribe(_rec.getvalue(), case.language)
        if _tr.get("text"):
            orch._log("VoiceAgent", f"Scribe {_tr.get('language_code') or ''} "
                      f"p={_tr.get('probability') or 'n/a'}: {len(_tr['text'])} chars")
            _handle_answer(_tr["text"], "voice", _tr)
            st.rerun()
        else:
            st.warning(f"Could not transcribe: {_tr.get('error', 'no speech detected')}")

    if case.dialect:
        st.markdown(f'<div class="panel"><div class="ptitle">DIALECT // HOW JARVIS HEARS YOU</div>'
                    f'<div class="fact"><b>VARIETY</b><span>{esc(case.dialect.get("variety", ""))}</span></div>'
                    f'<div class="fact"><b>CONFIDENCE</b><span>{esc(case.dialect.get("confidence", ""))}</span></div>'
                    + "".join(f'<div class="fact"><b>{esc(t.get("term", ""))}</b><span>{esc(t.get("likely_meaning", ""))}</span></div>'
                              for t in case.dialect.get("terms_to_clarify", []) or [])
                    + ('<div class="log">Interpreter recommended for legal steps.</div>'
                       if case.dialect.get("interpreter_recommended") else "")
                    + '</div>', unsafe_allow_html=True)

    rows = "".join(f'<div class="fact"><b>{esc(SLOT_LABELS.get(k, k)).upper()}</b><span>{esc(v)}</span></div>'
                   for k, v in case.facts.items()) or '<div class="log">No facts recorded yet.</div>'
    st.markdown(f'<div class="panel"><div class="ptitle">CASE FILE <span>{len(case.facts)} FACTS</span></div>{rows}</div>',
                unsafe_allow_html=True)

    # Entity confirmation widget
    if case.resolved_entity and not case.entity_confirmed and not case.entity_rejected:
        st.markdown(f"""
<div class="entity-confirm">
  <div class="ptitle">CONFIRM RESPONDENT</div>
  <div style="font-size:14px; color:#e9fbff;">Based on your account, the respondent appears to be:<br>
  <b style="color:var(--cyan); font-size:16px;">{esc(case.resolved_entity)}</b></div>
</div>""", unsafe_allow_html=True)
        ec1, ec2 = st.columns(2)
        with ec1:
            if st.button("CONFIRM ENTITY"):
                case.entity_confirmed = True
                case.facts["public_entity"] = case.resolved_entity
                orch._log("IntakeAgent", f"entity confirmed: {case.resolved_entity}")
                st.rerun()
        with ec2:
            if st.button("NOT CORRECT"):
                case.resolved_entity = None
                case.entity_rejected = True
                orch._log("IntakeAgent", "entity rejected by user — showing picker")
                st.rerun()

    # P0.3: After rejection, show a picker
    if case.entity_rejected and not case.entity_confirmed:
        st.markdown("""
<div class="entity-confirm">
  <div class="ptitle">SELECT RESPONDENT</div>
  <div style="font-size:13px; color:#e9fbff;">Which public entity is involved?</div>
</div>""", unsafe_allow_html=True)
        _entities = list_known_entities() + ["Other / not sure"]
        _pick = st.selectbox("Select respondent", _entities, key="entity_picker",
                             label_visibility="collapsed")
        if st.button("CONFIRM SELECTION"):
            if _pick == "Other / not sure":
                case.resolved_entity = None
                case.entity_confirmed = False
                orch._log("IntakeAgent", "entity: user unsure")
            else:
                case.resolved_entity = _pick
                case.entity_confirmed = True
                case.facts["public_entity"] = _pick
                orch._log("IntakeAgent", f"entity selected by user: {_pick}")
            st.rerun()

    if case.timeline:
        tl = "".join(f'<div><b>{esc(e.get("date", ""))}</b> {esc(e.get("event", ""))}</div>' for e in case.timeline)
        st.markdown(f'<div class="panel"><div class="ptitle">TIMELINE</div><div class="tl">{tl}</div></div>',
                    unsafe_allow_html=True)

# ------------------------------------------------------------------ CENTER: reactor
with center:
    n_agents = 5
    st.markdown(f'<div class="reactor-wrap"><div class="reactor">{reactor_svg(n_agents, case.progress())}</div></div>',
                unsafe_allow_html=True)
    status = "AWAITING ACCOUNT" if not case.facts else ("RESEARCH READY" if case.next_question() is None else "LISTENING")
    if orch.findings:
        status = "FINDINGS DELIVERED"
    st.markdown(f'<div class="status">{status}</div><div class="log" style="text-align:center">'
                f'{n_agents} AGENTS ONLINE · INTAKE {case.progress() * 100:.0f}%</div>', unsafe_allow_html=True)

    if case.areas:
        cards = ""
        for a in case.areas:
            name = a.area
            cards += (f'<div class="area"><div class="k">{LAW_AREAS[name]["icon"]}</div>'
                      f'<div class="n">{esc(name).upper()}</div><div class="bar"><i style="width:{a.score * 100:.0f}%"></i></div>'
                      f'<div class="n" style="color:#5f8ea3">{a.score:.0%} MATCH</div></div>')
        st.markdown(f'<div class="areas">{cards}</div>', unsafe_allow_html=True)
        why = [getattr(a, "why", "") for a in case.areas if getattr(a, "why", "")]
        if why:
            st.markdown(f'<div class="log" style="text-align:center;margin-top:8px">{esc(why[0])}</div>', unsafe_allow_html=True)

    if not st.session_state.voice_mode:
        # --- JARVIS VOICE button (glowing, centered) + standard buttons ---
        b1, b2, b3 = st.columns([1, 1.2, 1])
        with b1:
            if st.button("RUN RESEARCH", disabled=not all(k in case.facts for k in ("narrative", "where")) or not case.when_iso or not case.stage_report):
                st.session_state.run_research = True
                st.rerun()
        with b2:
            st.markdown("""
            <style>
            div[data-testid="stColumn"]:nth-child(2) .stButton>button#jarvis-voice-btn {
                background: radial-gradient(circle, rgba(41,230,255,.25), rgba(41,230,255,.05)) !important;
                border: 2px solid #29e6ff !important;
                color: #7ff3ff !important;
                font-size: 13px !important;
                padding: 14px 24px !important;
                box-shadow: 0 0 24px rgba(41,230,255,.5), 0 0 60px rgba(41,230,255,.15) !important;
                text-shadow: 0 0 8px rgba(41,230,255,.8);
                animation: voice-glow 2s ease-in-out infinite;
            }
            @keyframes voice-glow {
                0%,100% { box-shadow: 0 0 24px rgba(41,230,255,.4), 0 0 60px rgba(41,230,255,.1); }
                50% { box-shadow: 0 0 32px rgba(41,230,255,.7), 0 0 80px rgba(41,230,255,.25); }
            }
            </style>""", unsafe_allow_html=True)
            if st.button("◈  JARVIS VOICE  ◈", key="jarvis-voice-btn"):
                st.session_state.voice_mode = True
                st.rerun()
        with b3:
            if st.button("NEW CASE"):
                for k in ("case", "orch", "booted", "consent_given", "survey_open", "fp_lens"):
                    st.session_state.pop(k, None)
                st.rerun()
    else:
        # --- Voice mode ON: language dropdown + controls right under hologram ---
        _stt_lang = voice.STT_LANG_CODES.get(st.session_state.voice_lang, "en-US")

        # Language dropdown (prominent, centered)
        st.markdown("""
        <div style="text-align:center; margin-bottom:6px;">
          <span style="font-family:'Orbitron',sans-serif; font-size:10px; letter-spacing:.3em;
            color:#29e6ff;">VOICE LANGUAGE</span>
        </div>""", unsafe_allow_html=True)
        _lang_cols = st.columns([1, 2, 1])
        with _lang_cols[1]:
            new_lang = st.selectbox(
                "VOICE LANGUAGE", list(voice.LANGUAGES.keys()),
                index=list(voice.LANGUAGES.keys()).index(st.session_state.voice_lang),
                key="voice_lang_select", label_visibility="collapsed")
            if new_lang != st.session_state.voice_lang:
                st.session_state.voice_lang = new_lang
                case.language = new_lang
                st.rerun()

        # Buttons row
        v1, v2, v3 = st.columns(3)
        with v1:
            if st.button("RUN RESEARCH", disabled=not all(k in case.facts for k in ("narrative", "where")) or not case.when_iso or not case.stage_report, key="vrun"):
                st.session_state.run_research = True
                st.rerun()
        with v2:
            st.markdown("""
            <style>
            div[data-testid="stColumn"]:nth-child(2) button[kind="secondary"]:last-child {
                background: rgba(255,77,109,.12) !important;
                border-color: #ff4d6d !important;
                color: #ff4d6d !important;
            }
            </style>""", unsafe_allow_html=True)
            if st.button("VOICE MODE OFF", key="voff"):
                st.session_state.voice_mode = False
                st.rerun()
        with v3:
            if st.button("NEW CASE", key="vnew"):
                for k in ("case", "orch", "booted", "consent_given", "survey_open", "fp_lens"):
                    st.session_state.pop(k, None)
                st.rerun()

        # Auto-listen STT (hands-free, continuous)
        st.html(_voice_auto_listen_html(_stt_lang))

        # If research just completed and we have a voice summary, speak that instead
        _vsummary = st.session_state.pop("voice_summary", None)
        if _vsummary:
            _jarvis_speak(_vsummary)
        else:
            # Auto-speak latest Jarvis message (only once per message+language)
            _lmv = next((m for m in reversed(case.transcript) if m["role"] == "jarvis"), None)
            _last_j = (_lmv.get("text_local") or _lmv["text"]) if _lmv else None
            _spoken_key = f"_vspoken_{len(case.transcript)}_{case.language}"
            if _last_j and _spoken_key not in st.session_state:
                _jarvis_speak(_last_j, already_local=bool(_lmv.get("text_local")))
                st.session_state[_spoken_key] = True

# ------------------------------------------------------------------ RIGHT: flashpoint + sources + log
with right:
    _spec = lang_spec(case.language)
    _comm = _spec.get("community")
    _zip = ""
    import re as _re
    _m = _re.search(r"\b1\d{4}\b", case.facts.get("where", ""))
    if _m:
        _zip = _m.group(0)
    _descriptor = None
    if _comm:
        _loc = f"NYC ZIP {_zip}" if _zip else _comm["location"]
        _descriptor = f"{_comm['label']} · {_loc}"
    if not fp.live:
        if st.button("CONNECT FLASHPOINT (SIGN IN)", help="Opens your browser. Sign in with the account you used at app.flashpoint.ai."):
            from core.flashpoint import oauth_login
            with st.spinner("Waiting for you to sign in to Flashpoint in the browser…"):
                try:
                    oauth_login()
                    st.session_state.fp = FlashpointClient()
                    orch._log("FlashpointAgent", "signed in to Flashpoint (OAuth)")
                except Exception as e:
                    st.error(f"Flashpoint sign in failed: {e}")
            st.rerun()
    if st.button("FLASHPOINT // COMMUNITY LENS", disabled=_descriptor is None,
                 help="Live Flashpoint demographics for this language community. "
                      "Sends only the anonymous community description, never the person's story."):
        _q = (f"For {_comm['label']}: what share of residents are foreign born, speak "
              f"{case.language.split()[-1]} at home, and speak English less than very well? "
              "What does that imply for plain language and interpreter needs?")
        with st.spinner("Flashpoint.AI demographics (x402)"):
            _r = fp.demographics(_zip or _comm["location"], question=_q,
                                 audience=f"{case.language} speaking immigrants")
        _summary = _r.text
        if _r.data and isinstance(_r.data, dict):
            _summary = (_r.data.get("insights") or _r.data.get("summary") or _r.data.get("ai_insights")
                        or _json.dumps(_r.data, ensure_ascii=False)[:900])
            if isinstance(_summary, list):
                _summary = "\n".join(str(x) for x in _summary)
        st.session_state.fp_lens = {"source": _r.source, "summary": str(_summary)[:900], "ok": _r.ok}
        case.flashpoint = {"descriptor": _descriptor, "lens": st.session_state.fp_lens,
                           "cost": _r.cost_usdc}
        orch._log("FlashpointAgent", f"demographics {_r.source} ok={_r.ok} ({_r.seconds:.1f}s)")
        case.save()
        st.rerun()
    st.markdown(render_flashpoint_panel(
        {"live": fp.live, "address": fp.address or (fp.mode if fp.live else None),
         "spent": fp.spent_usdc()},
        st.session_state.get("fp_lens"), _calibration(), _descriptor, fp.log), unsafe_allow_html=True)
    _gm = _gap_map()
    if _gm:
        _rows = ""
        for g in _gm:
            def _bar(v, c):
                try:
                    v = float(str(v).strip("%"))
                except ValueError:
                    v = 0
                return (f'<div style="height:6px;background:rgba(41,230,255,.08);margin:2px 0">'
                        f'<i style="display:block;height:6px;width:{min(v,100):.0f}%;background:{c}"></i></div>')
            _rows += (f'<div class="fact" style="display:block"><b>{esc(g.get("topic","")).upper()}</b>'
                      f'<div class="log">SAY {esc(g.get("say_pct",""))}</div>{_bar(g.get("say_pct",0),"#29e6ff")}'
                      f'<div class="log">BELIEVE {esc(g.get("believe_pct",""))}</div>{_bar(g.get("believe_pct",0),"#ffb347")}'
                      f'<div class="log">DO {esc(g.get("do_pct",""))}</div>{_bar(g.get("do_pct",0),"#ff4d6d")}'
                      f'<div style="font-size:12px;color:#d8f6ff">{esc(g.get("gap",""))}</div></div>')
        st.markdown(f'<div class="panel"><div class="ptitle">SAY · BELIEVE · DO // {esc(case.language).upper()} COMMUNITY '
                    f'<span>FLASHPOINT PANEL</span></div>{_rows}</div>', unsafe_allow_html=True)

    all_sources = [s for f in orch.findings for s in f.sources]
    if all_sources:
        items = ""
        for s in all_sources[:14]:
            items += (f'<div class="src"><span class="tier t{s.tier}">T{s.tier} {TIER_LABELS[s.tier]}</span>'
                      f'<a href="{esc(s.url)}" target="_blank">{esc(s.title or s.domain)}</a>'
                      f'<div style="color:#5f8ea3">{esc(s.domain)} · {esc(s.agent)}</div></div>')
    else:
        items = '<div class="log">Sources appear here after research. Government and court sources rank first.</div>'
    st.markdown(f'<div class="panel"><div class="ptitle">SOURCE AUTHORITY <span>{len(all_sources)}</span></div>{items}</div>',
                unsafe_allow_html=True)

    log = "".join(f'<div>{e.t} <b>{esc(e.agent)}</b> {esc(e.msg)}</div>' for e in reversed(orch.log[-40:]))
    st.markdown(f'<div class="panel"><div class="ptitle">AGENT ACTIVITY</div><div class="log">{log}</div></div>',
                unsafe_allow_html=True)

# ------------------------------------------------------------------ ON THE SPOT SURVEY (security layer)
if st.session_state.get("survey_open") and not case.stage_report:
    st.write("")
    _rtl = lang_spec(case.language)["rtl"]
    st.markdown(f'<div class="panel"><div class="ptitle">ON THE SPOT CHECK // FLASHPOINT CALIBRATED SURVEY '
                f'<span>{esc(case.language).upper()}</span></div>'
                f'<div class="log">{esc(_local("This check is private: tap your answers, nobody hears them. What you said out loud and what you tap here are compared, so JARVIS catches any misunderstanding before research. You can answer I am not sure."))}</div>'
                f'<div class="log" style="color:#7ff3ff">SAY (voice intake) → BELIEVE / DO (private check) → GAP DETECTOR</div></div>',
                unsafe_allow_html=True)
    with st.spinner("Preparing the check in your language"):
        _summary_en = ("You told JARVIS: " + "; ".join(
            f"{SLOT_LABELS.get(k, k)}: {v}" for k, v in case.facts.items()
            if k in ("narrative", "notices", "filed", "goal", "helper")))[:600]
        _flat, _shape = [], []
        for item in SURVEY:
            q = item["q"] + ("\n\n" + _summary_en if item["id"] == "confirm" else "")
            _shape.append((item["id"], len(item["options"])))
            _flat += [q] + item["options"]
        _tr = dialect.translate_batch(_flat, case.language,
                                      (case.dialect or {}).get("variety", ""), _calibration())
        _items, _i = [], 0
        for sid, n in _shape:
            _items.append((sid, _tr[_i], _tr[_i + 1:_i + 1 + n]))
            _i += 1 + n
    with st.form("stage_survey"):
        _ans = {}
        for sid, q, opts in _items:
            _ans[sid] = st.radio(q, list(range(len(opts))), format_func=lambda i, o=opts: o[i],
                                 index=None, key=f"sv_{sid}")
        _submitted = st.form_submit_button("SUBMIT CHECK")
    if _submitted:
        _clean = {k: v for k, v in _ans.items() if v is not None}
        _rep = score_survey(_clean, " | ".join(case.facts.values()))
        case.survey_answers = _clean
        case.stage_report = _rep.as_dict()
        st.session_state.survey_open = False
        orch._log("SurveyAgent", f"stage={_rep.stage} verified={_rep.verified} "
                                 f"mismatches={len(_rep.mismatches)}")
        wfm.log_event(wf, "JARVIS + Flashpoint", f"triage: stage {_rep.stage}, verified={_rep.verified}, gaps={len(_rep.mismatches)}")
        if _rep.mismatches:
            _ask("Thank you. A few answers did not match what I understood earlier: "
                 + " ".join(_rep.mismatches) + " Please tell me in your own words what is correct.")
            case.pending_slot = "narrative"
        else:
            _ask(f"Thank you, I understood you correctly. You appear to be at this stage: "
                 f"{_rep.stage_label}. Press RUN RESEARCH or say 'run research' and I will look up "
                 "the procedure, the rules, and the official forms.")
        case.save()
        st.rerun()

if case.stage_report:
    st.write("")
    st.markdown(render_stage_map(case.stage_report), unsafe_allow_html=True)
    _c1, _c2 = st.columns([1, 5])
    with _c1:
        if st.button("RETAKE CHECK"):
            case.stage_report = {}
            st.session_state.survey_open = True
            st.rerun()


# ------------------------------------------------------------------ FIRM WORKFLOW (transparent)
if case.stage_report:
    st.write("")
    st.markdown('<div class="panel"><div class="ptitle">FIRM WORKFLOW // WHO DOES WHAT</div>'
                '<div class="log">JARVIS prepares; people decide. Conflict clearance, the consultation decision, '
                'and engagement are always signed off by staff.</div></div>', unsafe_allow_html=True)
    _t = st.tabs(["1.2 CONFLICT CHECK", "1.3 CONSULTATION", "1.4 ENGAGEMENT",
                  "2.1 MATTER", "2.2 DOCUMENTS", "2.3 READINESS AUDIT", "EVENT LOG"])

    # ---- 1.2 conflict check
    with _t[0]:
        st.caption("JARVIS screens names against the firm's client list (data/firm_clients.json). Staff clears. "
                   "Names stay on this computer.")
        _pp = st.text_area("Other people involved (one per line: family members, sponsor, employer, opposing party)",
                           value="\n".join(wf["conflict"].get("parties", [])), key="wf_parties", height=90)
        _cc1, _cc2 = st.columns(2)
        with _cc1:
            if st.button("RUN CONFLICT SCREEN"):
                parties = [p.strip() for p in _pp.splitlines() if p.strip()]
                wf["conflict"].update({"parties": parties, "hits": wfm.conflict_check(parties)})
                wf["conflict"]["status"] = "flag" if wf["conflict"]["hits"] else "screened"
                wfm.log_event(wf, "JARVIS", f"conflict screen: {len(parties)} names, {len(wf['conflict']['hits'])} possible hits")
                case.save(); st.rerun()
        for h in wf["conflict"].get("hits", []):
            st.markdown(f'<div class="alert warning">Possible conflict: <b>{esc(h["party"])}</b> matches '
                        f'{esc(h["as"])} <b>{esc(h["matched"])}</b> in matter {esc(h["matter"])}'
                        f'{" (exact)" if h["exact"] else " (close)"}</div>', unsafe_allow_html=True)
        if wf["conflict"]["status"] in ("screened", "flag"):
            with _cc2:
                _by = st.text_input("Cleared by (staff initials)", key="wf_clear_by")
                if st.button("STAFF: CLEAR CONFLICTS", disabled=not _by):
                    wf["conflict"].update({"status": "done", "cleared_by": _by})
                    wfm.log_event(wf, f"Staff {_by}", "conflicts cleared")
                    case.save(); st.rerun()
        if wf["conflict"]["status"] == "done":
            st.success(f"Cleared by {wf['conflict']['cleared_by']}")

    # ---- 1.3 consultation
    with _t[1]:
        st.caption("Attorney reviews history, current status and goals. Open LAWYER MODE (top right) for the "
                   "case summary, research chat and IRAC memo.")
        _rep = case.stage_report
        st.markdown(f"**Stage:** {_rep.get('stage_label')}  ·  **Concerns:** "
                    f"{', '.join(_rep.get('concerns', [])) or 'none stated'}  ·  **Language:** {case.language}")
        _cat_default = ("Removal defense" if _rep.get("stage") in ("court", "decision", "appeal")
                        else "Humanitarian (asylum, withholding, CAT)" if "asylum" in " ".join(case.facts.values()).lower()
                        else "Not yet decided")
        _cat = st.selectbox("Category (attorney decides)", wfm.CATEGORIES,
                            index=wfm.CATEGORIES.index(wf["consult"].get("category") or _cat_default), key="wf_cat")
        _att = st.text_input("Attorney", value=wf["consult"].get("attorney", ""), key="wf_att")
        _notes = st.text_area("Strategy notes (attorney only)", value=wf["consult"].get("notes", ""), key="wf_notes")
        if st.button("ATTORNEY: CONSULTATION COMPLETE", disabled=not _att or wf["conflict"]["status"] != "done"):
            wf["consult"].update({"status": "done", "category": _cat, "attorney": _att, "notes": _notes})
            wfm.log_event(wf, f"Attorney {_att}", f"consultation complete: {_cat}")
            case.save(); st.rerun()
        if wf["conflict"]["status"] != "done":
            st.info("Consultation unlocks after conflicts are cleared.")

    # ---- 1.4 engagement
    with _t[2]:
        st.caption("Retainer and fees are handled by people. JARVIS only drafts a summary for the attorney.")
        _fee = st.text_input("Fee arrangement", value=wf["engage"].get("fee", ""), key="wf_fee")
        _waiver = st.checkbox("Pro bono or fee waiver", value=wf["engage"].get("fee_waiver", False), key="wf_waiver")
        _draft = wfm.ENGAGEMENT_TEMPLATE.format(
            matter=wf["matter"].get("id") or "(assigned at matter creation)", language=case.language,
            interp="yes" if case.language != "English" else "not needed",
            category=wf["consult"].get("category") or "(pending consultation)",
            stage=case.stage_report.get("stage_label"), forms=", ".join(case.stage_report.get("forms", [])),
            fee=_fee or "(to be set)", waiver="yes" if _waiver else "no")
        st.download_button("DOWNLOAD DRAFT ENGAGEMENT SUMMARY", _draft, file_name="engagement_summary_DRAFT.txt")
        _signed = st.checkbox("Retainer agreement signed by client and attorney", key="wf_signed",
                              value=wf["engage"].get("retainer_signed", False))
        if st.button("STAFF: CLIENT ENGAGED", disabled=not _signed or wf["consult"]["status"] != "done"):
            wf["engage"].update({"status": "done", "retainer_signed": True, "fee": _fee, "fee_waiver": _waiver})
            wf["matter"] = {"status": "done", "id": wfm.matter_id(case)}
            wf["docs"]["status"] = "active"
            wfm.log_event(wf, "Staff", "client engaged; retainer signed")
            wfm.log_event(wf, "JARVIS", f"matter opened {wf['matter']['id']}")
            case.save(); st.rerun()

    # ---- 2.1 matter
    with _t[3]:
        if wf["matter"].get("id"):
            st.markdown(f'<div class="deadline-big">{esc(wf["matter"]["id"])}</div>', unsafe_allow_html=True)
            st.markdown(f"Folder: `{case.folder.name}` · Category: {wf['consult'].get('category')} · "
                        f"Attorney: {wf['consult'].get('attorney')} · Language: {case.language}")
        else:
            st.info("The matter opens automatically when the client is engaged.")

    # ---- 2.2 documents
    with _t[4]:
        if not wf["matter"].get("id"):
            st.info("Document collection starts after engagement.")
        else:
            _items = wfm.checklist(case, wf["consult"].get("category", ""))
            st.caption("Custom checklist for this category and stage. Files are saved only in the local "
                       "matter folder. Never upload SSN cards or bank statements unless the attorney asks.")
            _docdir = case.folder / "documents"
            for key_, label_en, required in _items:
                _label = _local(label_en)
                _have = wf["docs"]["uploads"].get(key_)
                st.markdown(f"{'✅' if _have else ('🔴' if required else '⚪')} **{esc(_label)}**"
                            + (f"  ·  _{esc(label_en)}_" if _label != label_en else "")
                            + ("" if required else "  (optional)"))
                _up = st.file_uploader(label_en, type=["pdf", "png", "jpg", "jpeg", "webp"],
                                       key=f"up_{key_}", label_visibility="collapsed")
                if _up is not None and (_have or {}).get("name") != _up.name:
                    _docdir.mkdir(parents=True, exist_ok=True)
                    _dest = _docdir / f"{key_}_{_up.name}"
                    _dest.write_bytes(_up.getvalue())
                    wf["docs"]["uploads"][key_] = {"name": _up.name, "path": str(_dest), "label": label_en}
                    wfm.log_event(wf, "Client", f"uploaded {label_en}")
                    case.save(); st.rerun()
            _req = [k for k, _, r in _items if r]
            _missing = [k for k in _req if k not in wf["docs"]["uploads"]]
            st.markdown(f"**{len(_req) - len(_missing)} of {len(_req)} required documents received.**")
            if not _missing and wf["docs"]["status"] != "done":
                wf["docs"]["status"] = "done"; case.save()

    # ---- 2.3 readiness audit
    with _t[5]:
        _ups = wf["docs"].get("uploads", {})
        if not _ups:
            st.info("The audit runs on uploaded documents.")
        else:
            if st.button("JARVIS: PRE AUDIT DOCUMENTS"):
                with st.spinner("Checking each document (quality and completeness only)"):
                    for k, u in _ups.items():
                        wf["audit"]["results"][k] = wfm.audit_document(Path(u["path"]), u["label"])
                wfm.log_event(wf, "JARVIS", f"pre audit of {len(_ups)} documents")
                case.save(); st.rerun()
            _usable, _problem = [], []
            for k, r in wf["audit"].get("results", {}).items():
                ok = r.get("matches_expected") and r.get("legible") and not r.get("red_flags")
                (_usable if ok else _problem).append((k, r))
            _items_all = {k: l for k, l, _ in wfm.checklist(case, wf["consult"].get("category", ""))}
            _missing = [l for k, l in _items_all.items() if k not in _ups]
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**READY**")
                for k, r in _usable:
                    st.markdown(f"✅ {esc(_items_all.get(k, k))}: {esc(r.get('summary', ''))}")
            with c2:
                st.markdown("**RED FLAGS / UNUSABLE**")
                for k, r in _problem:
                    st.markdown(f"⚠️ {esc(_items_all.get(k, k))}: " + "; ".join(esc(x) for x in r.get("red_flags", []) or ["does not match expected"]))
            with c3:
                st.markdown("**MISSING**")
                for l in _missing:
                    st.markdown(f"🔴 {esc(l)}")
            _by = st.text_input("Paralegal initials", key="wf_audit_by")
            if st.button("PARALEGAL: CONFIRM READINESS", disabled=not _by or not wf["audit"].get("results")):
                wf["audit"].update({"status": "done" if not _problem and not _missing else "flag", "confirmed_by": _by})
                wfm.log_event(wf, f"Paralegal {_by}", f"readiness {'confirmed' if wf['audit']['status'] == 'done' else 'flagged'}")
                case.save(); st.rerun()

    with _t[6]:
        st.markdown(render_events(wf), unsafe_allow_html=True)

# ------------------------------------------------------------------ FINDINGS (always shown)
if orch.findings:
    st.write("")
    cols = st.columns(len(orch.findings))
    for col, f in zip(cols, orch.findings):
        cls = {"verified": "ok", "partial": "warn"}.get(f.status, "bad")
        with col:
            st.markdown(f"""
<div class="panel"><div class="ptitle">{esc(f.title).upper()} <span>{esc(f.agent)}</span></div>
<span class="chip {cls}">{f.status.upper()}</span>
<div class="finding" style="margin-top:8px">{esc(f.body).replace(chr(10), "<br>")}</div></div>""", unsafe_allow_html=True)

    # Validator summary line
    st.markdown(render_validator_summary(orch.findings), unsafe_allow_html=True)

    # Educational disclaimer under findings
    st.markdown('<div class="disclaimer">JARVIS Immigration is an educational prototype. '
                'It shares general legal information only. Confirm all deadlines with a '
                'licensed attorney, legal aid, or a court help center.</div>',
                unsafe_allow_html=True)

# ------------------------------------------------------------------ NEXT STEP (exact match only)
_area = case.primary_area or ""
_resp = case.resolved_entity or ""
# P0.4: Only show next step on exact (domain, respondent) match with confirmed entity
_first_step = None
if _area and _resp and case.entity_confirmed:
    from core.deadlines import load_first_steps
    _steps = load_first_steps()
    _first_step = next((s for s in _steps
                        if s["domain"] == _area and s["respondent"] == _resp), None)

if _first_step and orch.findings:
    st.write("")
    st.markdown('<div class="panel"><div class="ptitle">NEXT STEP</div>', unsafe_allow_html=True)

    st.markdown(f'<div style="font-size:13px; color:var(--dim); letter-spacing:.1em;">RESPONDENT</div>'
                f'<div style="font-size:16px; color:#e9fbff; margin-bottom:10px;">{esc(_first_step["respondent"])}</div>',
                unsafe_allow_html=True)

    if case.when_iso:
        dl = compute_deadline(case.when_iso, _first_step["deadline_rule"])
        exp_cls = " expired" if dl.is_expired else ""
        days_text = "EXPIRED" if dl.is_expired else f"{dl.days_remaining} DAYS REMAINING"
        st.markdown(f'<div class="deadline-big{exp_cls}">{dl.deadline_date.strftime("%B %d, %Y")}</div>'
                    f'<div class="deadline-days" style="color:{"var(--bad)" if dl.is_expired else "var(--warn)"};">'
                    f'{days_text} ({dl.label})</div>', unsafe_allow_html=True)
        if dl.is_expired:
            st.markdown('<div class="disclaimer" style="color:#ff4d6d;">Other paths may exist. '
                        'Talk to a lawyer or Court Help Center now.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="deadline-big">EXACT DATE NEEDED</div>'
                    '<div class="deadline-days">Provide the exact incident date to compute your deadline.</div>',
                    unsafe_allow_html=True)

    if _first_step.get("needs_verification"):
        st.markdown('<div class="unverified">UNVERIFIED, UNDER REVIEW</div>', unsafe_allow_html=True)

    st.markdown(f'<div style="font-family:Orbitron; font-size:14px; color:var(--cyan); letter-spacing:.15em; '
                f'margin:12px 0 8px;">{esc(_first_step["first_step_title"]).upper()}</div>', unsafe_allow_html=True)

    for i, step in enumerate(_first_step["plain_language_steps"], 1):
        st.markdown(f'<div class="step-item"><span class="step-num">{i}.</span>{esc(step)}</div>',
                    unsafe_allow_html=True)

    if _first_step.get("where_to_file"):
        st.markdown(f'<div style="margin-top:10px; font-size:12px; color:var(--dim);">WHERE TO FILE</div>'
                    f'<div style="font-size:13px; color:#e9fbff;">{esc(_first_step["where_to_file"])}</div>',
                    unsafe_allow_html=True)

    if _first_step.get("citations"):
        cites = ""
        for c in _first_step["citations"]:
            t = c.get("tier", 5)
            cites += (f'<div class="src"><span class="tier t{t}">T{t}</span>'
                      f'<a href="{esc(c["url"])}" target="_blank">{esc(c["label"])}</a></div>')
        st.markdown(f'<div style="margin-top:10px;">{cites}</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

elif orch.findings and _area and _area != "Immigration":
    # No exact match — show help resources instead of wrong card
    st.markdown("""
    <div class="panel"><div class="ptitle">NEXT STEP</div>
    <div style="font-size:14px; color:#e9fbff;">
      No verified procedure on file for this respondent. For guidance:<br><br>
      <a href="https://www.nycourts.gov/courthelp/" target="_blank" style="color:var(--cyan);">NYC CourtHelp</a> ·
      <a href="https://www.lawhelpny.org/" target="_blank" style="color:var(--cyan);">LawHelpNY</a> ·
      <a href="https://www.nycbar.org/get-legal-help/" target="_blank" style="color:var(--cyan);">NYC Bar Legal Referral</a>
    </div></div>""", unsafe_allow_html=True)

# ------------------------------------------------------------------ LEGAL PROCEDURE MAP
if case.primary_area and case.primary_area != "Immigration" and not case.stage_report:
    _pub_mentioned = "public_entity" in case.facts or case.resolved_entity is not None
    _proc = select_procedure(
        case.primary_area,
        case.resolved_entity,
        case.entity_confirmed,
        public_entity_mentioned=_pub_mentioned,
    )
    if _proc:
        _actions = case.facts.get("actions_taken", "")
        # Build deadline data from the deadline engine
        _dl_data = {}
        if case.when_iso:
            for _stage in _proc.get("stages", []):
                _dref = _stage.get("deadline_ref")
                if _dref and _dref == "notice_of_claim_90d":
                    from core.deadlines import compute_deadline
                    _rule = {"type": "days", "days_or_months": 90,
                             "trigger": "incident_date"}
                    _dl = compute_deadline(case.when_iso, _rule)
                    _dl_data[_dref] = {
                        "date": _dl.deadline_date.strftime("%B %d, %Y"),
                        "days_remaining": _dl.days_remaining,
                        "expired": _dl.is_expired,
                    }
        _proc_result = locate_stages(case.facts, _actions, _proc, _dl_data)

        # Stage selector
        _stage_names = [s.stage["title"] for s in _proc_result.stages]
        _default_idx = max(_proc_result.current_index, 0)
        _selected = st.pills("Stage", _stage_names,
                             default=_stage_names[_default_idx] if _stage_names else None,
                             key="proc_stage_select", label_visibility="collapsed")
        _sel_idx = _stage_names.index(_selected) if _selected in _stage_names else _default_idx

        _map_html = render_procedure_map(_proc_result, selected_stage=_sel_idx)
        st.markdown(_map_html, unsafe_allow_html=True)

# ------------------------------------------------------------------ voice follow-up chat (after research)
if st.session_state.voice_mode and orch.findings and st.session_state.voice_messages:
    st.markdown("""
    <div class="panel"><div class="ptitle">JARVIS FOLLOW-UP · VOICE</div>
    <div style="font-size:12px; color:#d8f6ff;">
      Ask follow-up questions about your case. JARVIS is listening.</div></div>""",
                unsafe_allow_html=True)
    for m in st.session_state.voice_messages:
        who = "JARVIS" if m["role"] == "assistant" else USER.split()[0].upper()
        st.markdown(f'<div class="panel" style="margin-bottom:6px;">'
                    f'<div style="font-size:11px; color:var(--cyan); letter-spacing:.2em;">{who}</div>'
                    f'<div style="font-size:13px; color:#e9fbff; margin-top:4px; white-space:pre-wrap;">'
                    f'{esc(m["content"])}</div></div>', unsafe_allow_html=True)

    _followup = st.chat_input("Ask a follow-up question...", key="voice_followup")
    if _followup:
        st.session_state.voice_messages.append({"role": "user", "content": _followup})
        _lang = st.session_state.voice_lang
        _sys = (GUARDRAIL +
                f"\nYou are JARVIS, warm British manner.\nCase: {case.summary_text()}\n"
                f"Findings: {_build_findings_summary()}\n"
                f"Actions: {', '.join(_build_action_items())}\n"
                f"Respond in {_lang}. Under 150 words.")
        with st.spinner("JARVIS thinking..."):
            _reply = _claude_chat(st.session_state.voice_messages, system=_sys)
        st.session_state.voice_messages.append({"role": "assistant", "content": _reply})
        st.rerun()

    # Auto-speak last reply
    if st.session_state.voice_messages[-1]["role"] == "assistant":
        _sk = f"_vchat_spoken_{len(st.session_state.voice_messages)}_{st.session_state.voice_lang}"
        if _sk not in st.session_state:
            _jarvis_speak(st.session_state.voice_messages[-1]["content"])
            st.session_state[_sk] = True

with st.expander("TRANSCRIPT"):
    for m in case.transcript:
        who = "JARVIS" if m["role"] == "jarvis" else USER.split()[0].upper()
        _orig = m.get("text_local")
        _extra = f' <span style="color:#7ff3ff">[{esc(_orig)}]</span>' if _orig and _orig != m["text"] else ""
        st.markdown(f'<div class="log"><b>{who}</b> {esc(m["text"])}{_extra}</div>', unsafe_allow_html=True)
