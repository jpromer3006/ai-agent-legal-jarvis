"""Tests for orchestrator: safe_call, _ask_json replacement, classify fallback."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from core.orchestrator import Orchestrator, safe_call
from core.intake import CaseFile
from core.classifier import baseline_classify


class TestSafeCall:
    """safe_call wraps any callable with timeout, retry, and error capture."""

    def test_success(self):
        result = safe_call(lambda: 42)
        assert result == 42

    def test_returns_default_on_exception(self):
        def boom():
            raise RuntimeError("API down")
        result = safe_call(boom, default="fallback")
        assert result == "fallback"

    def test_retries_once(self):
        calls = []
        def flaky():
            calls.append(1)
            if len(calls) < 2:
                raise RuntimeError("transient")
            return "ok"
        result = safe_call(flaky, retries=1)
        assert result == "ok"
        assert len(calls) == 2

    def test_no_traceback_on_failure(self, capsys):
        """Failures should not print tracebacks."""
        safe_call(lambda: 1/0, default=None)
        captured = capsys.readouterr()
        assert "Traceback" not in captured.out
        assert "Traceback" not in captured.err


class TestClassifyFallback:
    """When the API call fails, classify should fall back to baseline."""

    def test_classify_with_broken_api(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.client = MagicMock()
        orch.client.messages.create.side_effect = RuntimeError("API error")
        orch.log = []
        orch.findings = []

        case = CaseFile.__new__(CaseFile)
        case.facts = {"narrative": "I fell on the subway and hurt my knee"}
        case.areas = []
        case.timeline = []
        case.transcript = []
        case.pending_slot = None
        case.when_iso = None
        case.when_raw = None
        case.resolved_entity = None
        case.entity_confirmed = False
        case.entity_rejected = False
        case.folder = None

        orch.classify(case)
        # Should have fallen back to baseline, not crashed
        assert len(case.areas) > 0
        assert any("Torts" in a.area for a in case.areas)


class TestExtractFactsMalformedJSON:
    """_ask_structured must handle tool use failures gracefully."""

    def test_malformed_response_does_not_crash(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.client = MagicMock()
        # Simulate a response with no tool_use block (model refused)
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I cannot extract facts from that."
        resp = MagicMock()
        resp.content = [text_block]
        resp.stop_reason = "end_turn"
        orch.client.messages.create.return_value = resp
        orch.log = []
        orch.findings = []

        case = CaseFile.__new__(CaseFile)
        case.facts = {}
        case.areas = []
        case.timeline = []
        case.transcript = []
        case.pending_slot = "narrative"
        case.when_iso = None
        case.when_raw = None
        case.resolved_entity = None
        case.entity_confirmed = False
        case.entity_rejected = False
        case.folder = None

        # Should not crash
        orch.extract_facts(case, "I slipped on the subway steps")
        assert "narrative" in case.facts
