"""ElevenLabs multilingual voice agent widget for the JARVIS HUD.

The agent itself (prompt, voice, six languages) lives in the ElevenLabs account
and is created by tools/create_voice_agent.py, which saves its id to
data/voice_agent.json. This module only embeds the agent's voice widget.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("jarvis")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "voice_agent.json"
WIDGET_SCRIPT = "https://unpkg.com/@elevenlabs/convai-widget-embed@0.22.2"
_AGENT_ID_PATTERN = re.compile(r"^agent_[A-Za-z0-9]{10,64}$")

LANGUAGE_NAMES = {"en": "English", "es": "Español", "zh": "中文", "hi": "हिन्दी",
                  "ru": "Русский", "ka": "ქართული", "ar": "العربية (مصري)"}


def load_agent_config(path: Path = CONFIG_PATH) -> dict | None:
    """Return the saved agent config, or None if missing or invalid."""
    if not path.exists():
        return None
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as err:
        logger.warning("voice agent config unreadable: %s", err)
        return None
    if not _AGENT_ID_PATTERN.match(str(config.get("agent_id", ""))):
        logger.warning("voice agent config has an invalid agent_id")
        return None
    return config


def widget_html(agent_id: str) -> str:
    """HTML that loads the ElevenLabs voice widget for one agent."""
    # Streamlit's HTML sanitizer drops unknown tags like <elevenlabs-convai>, so the
    # widget is created by script and attached to <body> once (Streamlit reruns often).
    if not _AGENT_ID_PATTERN.match(agent_id):
        raise ValueError("invalid ElevenLabs agent id")
    return f"""<script>
(function () {{
  const existing = document.querySelector('elevenlabs-convai');
  if (existing && existing.getAttribute('agent-id') === '{agent_id}') return;
  if (existing) existing.remove();
  const widget = document.createElement('elevenlabs-convai');
  widget.setAttribute('agent-id', '{agent_id}');
  document.body.appendChild(widget);
  if (!document.querySelector('script[data-jarvis-convai]')) {{
    const s = document.createElement('script');
    s.src = '{WIDGET_SCRIPT}';
    s.async = true;
    s.dataset.jarvisConvai = '1';
    document.body.appendChild(s);
  }}
}})();
</script>"""


def language_line(config: dict) -> str:
    """Readable list of the agent's languages, e.g. 'English · Español'."""
    return " · ".join(LANGUAGE_NAMES.get(c, c) for c in config.get("languages", ["en"]))
