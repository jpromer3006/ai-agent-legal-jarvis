"""Voice layer: ElevenLabs TTS + browser Web Speech STT + ElevenLabs Scribe STT.

English is the main language. Spanish, Georgian and Egyptian Arabic are the
test languages. Turbo v2.5 speaks English, Spanish and Arabic; Georgian uses
Eleven v3, and if that model is unavailable on the account ViaNova shows the
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

logger = logging.getLogger("vianova.voice")

# George: British, warm. The ViaNova persona across every language.
DEFAULT_VOICE_ID = os.getenv("ViaNova_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
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


_audio_counter = 0


def autoplay_audio_html(audio_b64: str) -> str:
    """Inject an audio element that plays after the user has interacted with the page.

    Chrome blocks autoplay until a user gesture occurs.  This function queues
    audio to window._vianovaAudioQueue if the gesture flag is not yet set, and
    drains the queue as soon as audio_enable_js() is injected (which happens
    right after the consent button click).
    """
    global _audio_counter
    _audio_counter += 1
    aid = f"vianova-audio-{_audio_counter}"
    return f"""
<audio id="{aid}" src="{audio_b64}" type="audio/mpeg" style="display:none"></audio>
<script>
(function(){{
  var audio = document.getElementById('{aid}');
  if (!audio) return;
  if (window._vianovaAudioEnabled) {{
    audio.play().catch(function(){{}});
  }} else {{
    window._vianovaAudioQueue = window._vianovaAudioQueue || [];
    window._vianovaAudioQueue.push(audio);
  }}
}})();
</script>"""


def audio_enable_js() -> str:
    """Return a one-time <script> that enables autoplay and drains the queue.

    Inject this immediately after the first user gesture (consent button click).
    """
    return """
<script>
(function(){
  window._vianovaAudioEnabled = true;
  var q = window._vianovaAudioQueue || [];
  window._vianovaAudioQueue = [];
  q.forEach(function(a){ a.play().catch(function(){}); });
})();
</script>"""
