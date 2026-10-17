"""JARVIS Legal OS: holographic command center (Streamlit).

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

from core.authority import TIER_LABELS
from core.classifier import LAW_AREAS
from core.deadlines import compute_deadline, find_first_step
from core.intake import (SLOT_LABELS, CaseFile, is_advice_seeking,
                         ADVICE_REFUSAL, list_known_entities)
from core.orchestrator import Orchestrator, MODEL, GUARDRAIL
from core import voice
from core.lawyer import claude_legal_chat, generate_irac_memo, memo_to_pdf

try:
    import anthropic as _anthropic_mod
except ImportError:
    _anthropic_mod = None

st.set_page_config(page_title="JARVIS Legal OS", page_icon="⚖️", layout="wide",
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
case: CaseFile = st.session_state.case
orch: Orchestrator = st.session_state.orch

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
    This system provides <b style="color:#29e6ff;">legal information</b>, not legal advice.<br>
    It does <b style="color:#ff4d6d;">not</b> replace a licensed attorney.<br>
    Always confirm deadlines with a legal aid or lawyer.<br>
    All responses are informational only.<br>
    <span style="color:#ffb347;">By continuing you acknowledge this disclaimer.</span>
  </div>
</div>""", unsafe_allow_html=True)
    if st.button("I UNDERSTAND — BEGIN INTAKE"):
        st.session_state.consent_given = True
        st.rerun()
    st.stop()


# ================================================================== VOICE MODE (overlay on dashboard)
def _jarvis_speak(text: str) -> None:
    """Speak text via ElevenLabs and auto-play in browser.

    If a non-English language is selected, translates before speaking so the
    ElevenLabs model renders the correct language with the British voice.
    """
    lang = st.session_state.get("voice_lang", "English")
    if lang != "English":
        translated = _claude_chat(
            [{"role": "user", "content": f"Translate to {lang}. Return ONLY the translation, nothing else:\n\n{text}"}],
            system="You are a translator. Output only the translated text."
        )
        text = translated
    audio_b64 = voice.speak_b64(text)
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

    # Top bar
    st.markdown(f"""
    <div class="topbar" style="border-color:rgba(255,215,0,.35);">
      <div class="brand" style="color:#ffd700; text-shadow:0 0 12px rgba(255,215,0,.6);">
        LAWYER MODE<small>CLAUDE LEGAL · IRAC MEMORANDUM</small></div>
      <div><span class="chip" style="color:#ffd700; border-color:#ffd700;">PRIVILEGED</span>
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
        # Save memo to case folder
        if case.folder:
            (case.folder / "irac_memo.txt").write_text(memo)
        st.rerun()

    # Display memo if generated
    if st.session_state.lawyer_memo:
        st.markdown("---")
        st.markdown("""
        <div class="lawyer-panel">
          <div class="lawyer-title">IRAC MEMORANDUM OF LAW</div>
        </div>""", unsafe_allow_html=True)
        st.markdown(f'<div class="memo-text">{esc(st.session_state.lawyer_memo)}</div>',
                    unsafe_allow_html=True)

        # PDF download
        if st.session_state.pop("_download_pdf", False) or True:
            _area = case.primary_area or "Legal Matter"
            _pdf = memo_to_pdf(st.session_state.lawyer_memo, f"Memorandum — {_area}")
            st.download_button(
                label="DOWNLOAD MEMO AS PDF",
                data=_pdf,
                file_name=f"IRAC_Memo_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
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
    case.transcript.append({"role": "jarvis", "text": "Good day. I'm JARVIS. I'll take an account of what happened, "
                            "identify which areas of law may apply, and show you the official sources. " + q})

# ------------------------------------------------------------------ input handling
answer = st.chat_input("Speak to JARVIS (or click JARVIS VOICE for full voice mode)")
if answer:
    _cmd = answer.strip().lower()
    # Intercept commands before they reach slot filling
    _RESEARCH_CMDS = {"run research", "research", "jarvis run research"}
    _FIRST_STEP_CMDS = {"what do i do first", "what should i do", "first step",
                        "what do i do", "next step", "what now"}
    if _cmd in _RESEARCH_CMDS:
        case.transcript.append({"role": "user", "text": answer})
        st.session_state.run_research = True
        st.rerun()
    elif _cmd in _FIRST_STEP_CMDS:
        case.transcript.append({"role": "user", "text": answer})
        st.session_state.show_first_step_chat = True
        st.rerun()
    elif is_advice_seeking(answer):
        # P1.4: Intent gate — refuse advice, re-ask pending question
        case.transcript.append({"role": "user", "text": answer})
        _pending_q = ""
        if case.pending_slot:
            nxt = case.next_question()
            _pending_q = f"\n\n{nxt[1]}" if nxt else ""
        case.transcript.append({"role": "jarvis", "text": ADVICE_REFUSAL + _pending_q})
        st.rerun()
    else:
        with st.spinner("JARVIS processing"):
            orch.extract_facts(case, answer)
            orch.classify(case)
            nxt = case.next_question()
            if nxt:
                case.pending_slot, q = nxt
                # If date was vague, ask for exact date
                if case.when_raw and not case.when_iso:
                    q = (f"I need an exact date to compute deadlines. "
                         f"You said \"{case.when_raw}\" — can you give me "
                         f"the specific date (month, day, year)?")
                    case.pending_slot = "when"
                    case.facts.pop("when", None)
                case.transcript.append({"role": "jarvis", "text": q})
            else:
                case.pending_slot = None
                case.transcript.append({"role": "jarvis", "text": "Intake complete. Say \"run research\" or press RUN RESEARCH and I'll dispatch the agents."})
            case.save()
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
    _area = case.primary_area or "Torts / Personal Injury"
    _resp = case.resolved_entity or ""
    _fs = find_first_step(_area, _resp)
    if _fs and case.when_iso:
        _dl = compute_deadline(case.when_iso, _fs["deadline_rule"])
        _msg = (f"{_fs['first_step_title']}. Your deadline is {_dl.deadline_date.strftime('%B %d, %Y')} "
                f"({'EXPIRED' if _dl.is_expired else f'{_dl.days_remaining} days remaining'}). "
                f"Step 1: {_fs['plain_language_steps'][0]}")
    elif _fs:
        _msg = (f"{_fs['first_step_title']}. I need the incident date to compute your deadline. "
                f"Step 1: {_fs['plain_language_steps'][0]}")
    else:
        _msg = "I don't have enough information yet to identify your first step. Please complete the intake questions."
    case.transcript.append({"role": "jarvis", "text": _msg})

# ------------------------------------------------------------------ top bar
mode = '<span class="chip ok">ONLINE</span>' if orch.online else '<span class="chip warn">OFFLINE DEMO</span>'
_voice_chip = (f'<span class="chip ok">VOICE: ON · {esc(st.session_state.voice_lang).upper()}</span>'
               if st.session_state.voice_mode
               else '<span class="chip">VOICE: OFF</span>')
_tb_left, _tb_right = st.columns([4, 1])
with _tb_left:
    st.markdown(f"""
    <div class="topbar">
      <div class="brand">J.A.R.V.I.S.<small>LEGAL OS · v0.1 · INTAKE + RESEARCH CORE</small></div>
      <div>{mode}<span class="chip">USER: {esc(USER).upper()}</span><span class="chip">CASE {esc(case.created)}</span>
      <span class="chip">{time.strftime('%a %b %d  %H:%M')}</span>{_voice_chip}</div>
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
    if st.button("LAWYER MODE", key="lawyer-btn"):
        st.session_state.lawyer_mode = True
        st.rerun()
st.write("")

# ================================================================== LAWYER MODE
if st.session_state.lawyer_mode:
    _lawyer_mode_ui()
    st.stop()

left, center, right = st.columns([1.15, 1.3, 1.15], gap="medium")

# ------------------------------------------------------------------ LEFT: intake
with left:
    last_q = next((m["text"] for m in reversed(case.transcript) if m["role"] == "jarvis"), "")
    prog = case.progress()
    st.markdown(f"""
<div class="panel"><div class="ptitle">INTAKE // CURRENT QUERY <span>{prog * 100:.0f}%</span></div>
<div class="question">{esc(last_q)}</div>
<div class="bar"><i style="width:{prog * 100:.0f}%"></i></div></div>""", unsafe_allow_html=True)

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
            if st.button("RUN RESEARCH", disabled=not all(k in case.facts for k in ("narrative", "where")) or not case.when_iso):
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
                for k in ("case", "orch", "booted", "consent_given"):
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
                st.rerun()

        # Buttons row
        v1, v2, v3 = st.columns(3)
        with v1:
            if st.button("RUN RESEARCH", disabled=not all(k in case.facts for k in ("narrative", "where")) or not case.when_iso, key="vrun"):
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
                for k in ("case", "orch", "booted", "consent_given"):
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
            _last_j = next((m["text"] for m in reversed(case.transcript) if m["role"] == "jarvis"), None)
            _spoken_key = f"_vspoken_{len(case.transcript)}_{st.session_state.voice_lang}"
            if _last_j and _spoken_key not in st.session_state:
                _jarvis_speak(_last_j)
                st.session_state[_spoken_key] = True

# ------------------------------------------------------------------ RIGHT: sources + log
with right:
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
<div class="finding" style="margin-top:8px">{esc(f.body)}</div></div>""", unsafe_allow_html=True)

    # Educational disclaimer under findings
    st.markdown('<div class="disclaimer">JARVIS Legal OS is an educational prototype. '
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

elif orch.findings and _area:
    # No exact match — show help resources instead of wrong card
    st.markdown("""
    <div class="panel"><div class="ptitle">NEXT STEP</div>
    <div style="font-size:14px; color:#e9fbff;">
      No verified procedure on file for this respondent. For guidance:<br><br>
      <a href="https://www.nycourts.gov/courthelp/" target="_blank" style="color:var(--cyan);">NYC CourtHelp</a> ·
      <a href="https://www.lawhelpny.org/" target="_blank" style="color:var(--cyan);">LawHelpNY</a> ·
      <a href="https://www.nycbar.org/get-legal-help/" target="_blank" style="color:var(--cyan);">NYC Bar Legal Referral</a>
    </div></div>""", unsafe_allow_html=True)

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
        st.markdown(f'<div class="log"><b>{who}</b> {esc(m["text"])}</div>', unsafe_allow_html=True)
