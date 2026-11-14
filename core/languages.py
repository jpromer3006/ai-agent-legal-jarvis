"""Language registry for JARVIS Immigration.

English is the main language of the app and of the case file. Spanish,
Georgian and Egyptian Arabic are the three test languages. Every answer is
kept in the original words AND translated to English for the case file, so a
lawyer always reads English while the person always hears their own language.
"""
from __future__ import annotations

LANGUAGES: dict[str, dict] = {
    "English": {
        "native": "English", "web_stt": "en-US", "scribe": "eng",
        "tts_model": "eleven_turbo_v2_5", "rtl": False,
        "dialect_hint": "American English; watch for plain language needs.",
        "community": None,
    },
    "Spanish": {
        "native": "Español", "web_stt": "es-US", "scribe": "spa",
        "tts_model": "eleven_turbo_v2_5", "rtl": False,
        "dialect_hint": ("Latin American Spanish. Distinguish Mexican, Dominican, "
                         "Ecuadorian (Andean, possible Kichwa loanwords), Guatemalan "
                         "(possible K'iche' or Mam first language), Venezuelan, Colombian. "
                         "Common immigration slang: 'papeles', 'la migra', 'la corte', "
                         "'el asilo', 'permiso de trabajo', 'notario'."),
        "community": {"label": "Spanish speaking immigrants, Bushwick and Corona",
                      "location": "Corona, Queens, NY 11368"},
    },
    "Georgian": {
        "native": "ქართული", "web_stt": "ka-GE", "scribe": "kat",
        # Turbo v2.5 has no Georgian; Eleven v3 covers it. Falls back to text.
        "tts_model": "eleven_v3", "rtl": False,
        "dialect_hint": ("Georgian (Kartuli). Many recent arrivals in South Brooklyn "
                         "(Brighton Beach, Sheepshead Bay); some also speak Russian. "
                         "Few court interpreters, so plain wording matters."),
        "community": {"label": "Georgian speaking immigrants, South Brooklyn",
                      "location": "Brighton Beach, Brooklyn, NY 11235"},
    },
    "Egyptian Arabic": {
        "native": "العربية المصرية", "web_stt": "ar-EG", "scribe": "ara",
        "tts_model": "eleven_turbo_v2_5", "rtl": True,
        "dialect_hint": ("Egyptian Arabic (Masri), not Modern Standard Arabic. Use "
                         "colloquial forms (e.g. 'عايز' not 'أريد', 'إزاي' not 'كيف'). "
                         "Community centered in Astoria and Bay Ridge."),
        "community": {"label": "Egyptian Arabic speaking immigrants, Astoria and Bay Ridge",
                      "location": "Astoria, Queens, NY 11103"},
    },
}

TEST_LANGUAGES = ["Spanish", "Georgian", "Egyptian Arabic"]


def lang(name: str) -> dict:
    return LANGUAGES.get(name, LANGUAGES["English"])


def from_scribe_code(code: str | None) -> str:
    """Map an ElevenLabs Scribe language code back to our registry name."""
    if not code:
        return "English"
    code = code.lower()
    for name, spec in LANGUAGES.items():
        if spec["scribe"] == code or spec["web_stt"].lower().startswith(code[:2]):
            return name
    return "English"
