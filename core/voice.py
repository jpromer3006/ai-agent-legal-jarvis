"""Voice layer: ElevenLabs TTS + browser Web Speech API STT.

TTS uses ElevenLabs Turbo v2.5 (multi-language) with a British voice for
the JARVIS persona. Supports English, Spanish, Mandarin, and Hindi — all
spoken with the same British accent.

STT uses the browser's built-in Web Speech API via a custom Streamlit HTML
component (no server-side mic needed).
"""
from __future__ import annotations

import base64
import os
from io import BytesIO

try:
    from elevenlabs import ElevenLabs
except ImportError:
    ElevenLabs = None

# George — British, warm storyteller. Best Jarvis fit.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
MODEL_ID = "eleven_turbo_v2_5"  # multi-language: EN, ES, ZH, HI + 28 more

LANGUAGES = {
    "English":  "en",
    "Spanish":  "es",
    "Mandarin": "zh",
    "Hindi":    "hi",
}

# Web Speech API language codes for STT
STT_LANG_CODES = {
    "English":  "en-US",
    "Spanish":  "es-ES",
    "Mandarin": "zh-CN",
    "Hindi":    "hi-IN",
}


def _get_client() -> "ElevenLabs | None":
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key or ElevenLabs is None:
        return None
    return ElevenLabs(api_key=key)


def speak(text: str, voice_id: str | None = None) -> bytes | None:
    """Convert text to speech via ElevenLabs. Returns mp3 bytes or None."""
    client = _get_client()
    if client is None:
        return None
    audio_iter = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id or DEFAULT_VOICE_ID,
        model_id=MODEL_ID,
        output_format="mp3_44100_128",
    )
    buf = BytesIO()
    for chunk in audio_iter:
        buf.write(chunk)
    return buf.getvalue()


def speak_b64(text: str, voice_id: str | None = None) -> str | None:
    """Like speak() but returns a base64-encoded data URI for embedding in HTML."""
    audio = speak(text, voice_id)
    if audio is None:
        return None
    return "data:audio/mpeg;base64," + base64.b64encode(audio).decode()


def autoplay_audio_html(audio_b64: str) -> str:
    """Return an HTML snippet that auto-plays a base64 audio clip."""
    return f"""
    <audio autoplay>
      <source src="{audio_b64}" type="audio/mpeg">
    </audio>"""


