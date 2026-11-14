"""Tests for the ElevenLabs voice agent widget helpers."""
import json

import pytest

from ui.voice_agent import language_line, load_agent_config, widget_html

GOOD_ID = "agent_0000example0000test"


def test_load_agent_config_valid(tmp_path):
    p = tmp_path / "voice_agent.json"
    p.write_text(json.dumps({"agent_id": GOOD_ID, "languages": ["en", "ka"]}))
    assert load_agent_config(p)["agent_id"] == GOOD_ID


def test_load_agent_config_missing_file(tmp_path):
    assert load_agent_config(tmp_path / "nope.json") is None


def test_load_agent_config_rejects_bad_id(tmp_path):
    p = tmp_path / "voice_agent.json"
    p.write_text(json.dumps({"agent_id": '"><script>alert(1)</script>'}))
    assert load_agent_config(p) is None


def test_load_agent_config_rejects_broken_json(tmp_path):
    p = tmp_path / "voice_agent.json"
    p.write_text("{not json")
    assert load_agent_config(p) is None


def test_widget_html_contains_agent_and_pinned_script():
    html = widget_html(GOOD_ID)
    assert f"'agent-id', '{GOOD_ID}'" in html
    assert "createElement('elevenlabs-convai')" in html
    assert "convai-widget-embed@" in html


def test_widget_html_rejects_injection():
    with pytest.raises(ValueError):
        widget_html('x" onload="alert(1)')


def test_language_line():
    assert language_line({"languages": ["en", "ka"]}) == "English · ქართული"
    assert language_line({}) == "English"
