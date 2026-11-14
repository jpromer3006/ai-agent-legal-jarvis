"""Voice layer: ElevenLabs TTS + browser Web Speech STT + ElevenLabs Scribe STT.

English is the main language. Spanish, Georgian and Egyptian Arabic are the
test languages. Turbo v2.5 speaks English, Spanish and Arabic; Georgian uses
Eleven v3, and if that model is unavailable on the account Jarvis shows the
Georgian text on screen instead of speaking it.
"""
from __future__ import annotations

import base64
import logging
import os
from io import BytesIO

from .languages import LANGUAGES, lang

try:
    from elevenlabs import ElevenLabs
except ImportError:
    ElevenLabs = None

logger = logging.getLogger("jarvis.voice")

# George: British, warm. The JARVIS persona across every language.
DEFAULT_VOICE_ID = os.getenv("JARVIS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
MODEL_ID = "eleven_turbo_v2_5"

# Backward compatible maps used by app.py
STT_LANG_CODES = {name: spec["web_stt"] for name, spec in LANGUAGES.items()}


def _get_client() -> "ElevenLabs | None":
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key or ElevenLabs is None:
        return None
    return ElevenLabs(api_key=key)


def speak(text: str, voice_id: str | None = None, language: str = "English") -> bytes | None:
    """Text to speech. Returns mp3 bytes, or None if this language can't be voiced."""
    client = _get_client()
    if client is None or not text.strip():
        return None
    models = [lang(language)["tts_model"]]
    if MODEL_ID not in models and language != "Georgian":
        models.append(MODEL_ID)
    for model in models:
        try:
            audio_iter = client.text_to_speech.convert(
                text=text, voice_id=voice_id or DEFAULT_VOICE_ID,
                model_id=model, output_format="mp3_44100_128")
            buf = BytesIO()
            for chunk in audio_iter:
                buf.write(chunk)
            return buf.getvalue()
        except Exception as e:
            logger.warning("TTS %s failed for %s: %s", model, language, e)
    return None


def speak_b64(text: str, voice_id: str | None = None, language: str = "English") -> str | None:
    audio = speak(text, voice_id, language)
    if audio is None:
        return None
    return "data:audio/mpeg;base64," + base64.b64encode(audio).decode()


def autoplay_audio_html(audio_b64: str) -> str:
    return f"""
    <audio autoplay>
      <source src="{audio_b64}" type="audio/mpeg">
    </audio>"""
