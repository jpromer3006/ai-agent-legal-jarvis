"""Voice transcription + dialect understanding layer.

1. transcribe()       ElevenLabs Scribe speech to text with language detection
                      (uses the existing ELEVENLABS_API_KEY).
2. analyze_dialect()  Claude reads the transcript and names the language
                      variety, register, and words that need care, and gives an
                      English rendering for the case file.
3. render_question()  Rewrites Jarvis's next question in the person's own
                      dialect, using the Flashpoint community calibration notes.

Hard rule: dialect analysis is used ONLY to understand and to be understood.
It never estimates nationality, credibility, or immigration status.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from io import BytesIO

from .languages import LANGUAGES, from_scribe_code, lang

logger = logging.getLogger("jarvis.dialect")

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

FAST_MODEL = os.getenv("JARVIS_FAST_MODEL", "claude-haiku-4-5-20251001")

DIALECT_RULES = """You support an immigration legal INFORMATION intake (not advice).
You analyze HOW a person speaks only so the assistant understands them and is
understood. Never infer or comment on nationality, ethnicity, credibility,
truthfulness, or immigration status from language or dialect. If unsure, say so."""

DIALECT_TOOL = {
    "name": "dialect_profile",
    "description": "Describe the language variety in a transcript and render it in English.",
    "input_schema": {
        "type": "object",
        "properties": {
            "language": {"type": "string", "enum": list(LANGUAGES)},
            "variety": {"type": "string",
                        "description": "Regional variety, e.g. 'Ecuadorian Andean Spanish', "
                                       "'Egyptian Arabic (Cairene)', 'Standard Georgian'. "
                                       "'uncertain' if not clear."},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "register": {"type": "string", "description": "formal, everyday, very informal"},
            "plain_language_needed": {"type": "boolean"},
            "interpreter_recommended": {"type": "boolean"},
            "terms_to_clarify": {
                "type": "array", "maxItems": 6,
                "items": {"type": "object", "properties": {
                    "term": {"type": "string"}, "likely_meaning": {"type": "string"}},
                    "required": ["term", "likely_meaning"]}},
            "english": {"type": "string", "description": "Faithful English rendering of the transcript."},
        },
        "required": ["language", "variety", "confidence", "english"],
    },
}


def _client():
    key = os.getenv("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key) if (key and anthropic) else None


# ------------------------------------------------------------ transcription
def transcribe(audio_bytes: bytes, hint_language: str | None = None) -> dict:
    """ElevenLabs Scribe STT. Returns {text, language, language_code, probability}."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return {"text": "", "language": hint_language or "English", "error": "ELEVENLABS_API_KEY missing"}
    try:
        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=key)
        kwargs = {"file": BytesIO(audio_bytes)}
        if hint_language and hint_language != "auto":
            kwargs["language_code"] = lang(hint_language)["scribe"]
        res, last_err = None, None
        for model in (os.getenv("JARVIS_STT_MODEL", "scribe_v2"), "scribe_v1"):
            try:
                kwargs["file"] = BytesIO(audio_bytes)
                res = client.speech_to_text.convert(model_id=model, **kwargs)
                break
            except Exception as e:  # try the older model id
                last_err = e
        if res is None:
            raise last_err
        code = getattr(res, "language_code", None)
        return {"text": getattr(res, "text", "") or "",
                "language_code": code,
                "language": hint_language if hint_language and hint_language != "auto" else from_scribe_code(code),
                "probability": getattr(res, "language_probability", None)}
    except Exception as e:
        logger.warning("transcribe failed: %s", e)
        return {"text": "", "language": hint_language or "English", "error": str(e)}


# ------------------------------------------------------------ dialect
def analyze_dialect(text: str, language: str) -> dict:
    """Claude dialect profile + English rendering. Offline: passthrough."""
    client = _client()
    if not client or not text.strip():
        return {"language": language, "variety": "uncertain", "confidence": "low",
                "english": text, "offline": True}
    try:
        resp = client.messages.create(
            model=FAST_MODEL, max_tokens=900, system=DIALECT_RULES,
            messages=[{"role": "user", "content":
                       f"Expected language: {language}. Hints: {lang(language)['dialect_hint']}\n"
                       f"Transcript:\n{text}"}],
            tools=[DIALECT_TOOL], tool_choice={"type": "tool", "name": "dialect_profile"})
        for b in resp.content:
            if b.type == "tool_use":
                return dict(b.input)
    except Exception as e:
        logger.warning("analyze_dialect failed: %s", e)
    return {"language": language, "variety": "uncertain", "confidence": "low", "english": text}


@lru_cache(maxsize=512)
def translate(text: str, target: str, variety: str = "", calibration: str = "") -> str:
    """Translate English into the target language variety (cached)."""
    if target == "English" or not text.strip():
        return text
    client = _client()
    if not client:
        return text
    spec = lang(target)
    try:
        resp = client.messages.create(
            model=FAST_MODEL, max_tokens=800,
            system=("You translate an immigration legal information assistant's words for "
                    "a person who may have limited formal schooling. Use everyday spoken "
                    "wording in the requested variety, short sentences, no legal jargon "
                    "without a plain explanation in parentheses. Keep form numbers and "
                    "agency names (USCIS, I-589, immigration court) as they are. "
                    "Output only the translation."),
            messages=[{"role": "user", "content":
                       f"Target: {target} ({variety or spec['dialect_hint']}).\n"
                       f"Community calibration notes from survey research: {calibration or 'none'}\n\n"
                       f"Text:\n{text}"}])
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        logger.warning("translate failed: %s", e)
        return text


_BATCH_CACHE: dict = {}


def translate_batch(texts: list[str], target: str, variety: str = "",
                    calibration: str = "") -> list[str]:
    """Translate many short strings in ONE call (survey questions + options)."""
    if target == "English" or not texts:
        return list(texts)
    key = (tuple(texts), target, variety, calibration)
    if key in _BATCH_CACHE:
        return _BATCH_CACHE[key]
    client = _client()
    if not client:
        return list(texts)
    spec = lang(target)
    try:
        resp = client.messages.create(
            model=FAST_MODEL, max_tokens=4000,
            system=("Translate each string for a person who may have limited formal schooling. "
                    "Everyday spoken wording in the requested variety, short and clear. Keep "
                    "agency names and form numbers. Return ONLY a JSON array of strings, same "
                    "length and order as the input."),
            messages=[{"role": "user", "content":
                       f"Target: {target} ({variety or spec['dialect_hint']}).\n"
                       f"Community calibration notes: {calibration or 'none'}\n"
                       f"Strings:\n{json.dumps(texts, ensure_ascii=False)}"}])
        out = "".join(b.text for b in resp.content if b.type == "text").strip()
        out = out[out.index("["): out.rindex("]") + 1]
        arr = json.loads(out)
        if isinstance(arr, list) and len(arr) == len(texts):
            _BATCH_CACHE[key] = [str(x) for x in arr]
            return _BATCH_CACHE[key]
    except Exception as e:
        logger.warning("translate_batch failed: %s", e)
    return list(texts)


def render_question(question_en: str, language: str, profile: dict | None,
                    calibration: str = "") -> str:
    """Jarvis's next question in the person's own variety."""
    variety = (profile or {}).get("variety", "")
    if variety == "uncertain":
        variety = ""
    return translate(question_en, language, variety, calibration)


def to_english(text: str, language: str) -> tuple[str, dict]:
    """Normalize a typed or spoken answer to English for the case file."""
    if language == "English":
        return text, {"language": "English", "variety": "", "confidence": "high", "english": text}
    prof = analyze_dialect(text, language)
    return prof.get("english") or text, prof


def profile_badge(profile: dict | None) -> str:
    if not profile:
        return ""
    return f"{profile.get('language', '')} · {profile.get('variety', '')} · {profile.get('confidence', '')} confidence"


def dumps(profile: dict) -> str:
    return json.dumps(profile, ensure_ascii=False, indent=2)
