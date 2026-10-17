"""Tests for procedure engine: select_procedure and locate_stages."""
from __future__ import annotations

import pytest

from core.procedure import select_procedure, locate_stages, _check_signals


class TestSelectProcedure:
    def test_nyct_tort_matches_public_entity(self):
        proc = select_procedure("Torts / Personal Injury",
                                "New York City Transit Authority", True)
        assert proc is not None
        assert proc["id"] == "nyc-public-entity-tort"

    def test_city_of_ny_matches_public_entity(self):
        proc = select_procedure("Torts / Personal Injury",
                                "City of New York", True)
        assert proc is not None
        assert proc["id"] == "nyc-public-entity-tort"

    def test_private_party_when_no_entity(self):
        proc = select_procedure("Torts / Personal Injury", None, False)
        assert proc is not None
        assert proc["id"] == "private-party-injury"

    def test_private_party_when_unconfirmed(self):
        proc = select_procedure("Torts / Personal Injury",
                                "Some Entity", False)
        assert proc is not None
        assert proc["id"] == "private-party-injury"

    def test_unknown_area_gets_fallback(self):
        proc = select_procedure("Unknown Area", None, False)
        assert proc is not None
        assert proc["id"] == "generic-fallback"

    def test_housing_gets_fallback(self):
        """No specific housing procedure defined — should fall back."""
        proc = select_procedure("Housing / Landlord Tenant", None, False)
        assert proc is not None
        assert proc["id"] == "generic-fallback"

    def test_lirr_not_in_public_entity_list(self):
        """LIRR is not in the NYC public entity procedure — should get private."""
        proc = select_procedure("Torts / Personal Injury",
                                "Long Island Rail Road", True)
        # LIRR is not in the applies_when list, so should NOT match nyc-public-entity
        assert proc is not None
        assert proc["id"] != "nyc-public-entity-tort"

    # Cleanup 3 item 2: public entity always gets public procedure
    def test_confirmed_public_entity_gets_public_procedure(self):
        """When a public entity IS resolved and confirmed, use public entity procedure."""
        proc = select_procedure("Torts / Personal Injury",
                                "City of New York", True)
        assert proc["id"] == "nyc-public-entity-tort"

    def test_unknown_respondent_gets_fallback_not_private(self):
        """When respondent is unknown but public entity mentioned, use fallback."""
        proc = select_procedure("Torts / Personal Injury", None, False,
                                public_entity_mentioned=True)
        assert proc is not None
        assert proc["id"] != "private-party-injury"
        assert proc["id"] == "generic-fallback"


class TestLocateStages:
    def test_incident_done_when_narrative_exists(self):
        proc = select_procedure("Torts / Personal Injury", None, False)
        result = locate_stages({"narrative": "I fell"}, "", proc)
        assert result.stages[0].status == "done"
        assert result.stages[1].status == "current"

    def test_no_facts_first_stage_is_current(self):
        proc = select_procedure("Torts / Personal Injury", None, False)
        result = locate_stages({}, "", proc)
        assert result.stages[0].status == "current"
        assert result.current_index == 0

    def test_actions_filed_marks_stage_done(self):
        proc = select_procedure("Torts / Personal Injury", None, False)
        result = locate_stages(
            {"narrative": "I fell", "actions_taken": "I filed a demand letter"},
            "I filed a demand letter", proc
        )
        # Incident done, demand done, next is current
        assert result.stages[0].status == "done"  # incident
        assert result.stages[1].status == "done"  # demand/insurance
        assert result.stages[2].status == "current"  # summons

    def test_deadline_data_attached(self):
        proc = select_procedure("Torts / Personal Injury",
                                "City of New York", True)
        dl_data = {
            "notice_of_claim_90d": {
                "date": "January 15, 2027",
                "days_remaining": 60,
                "expired": False,
            }
        }
        result = locate_stages({"narrative": "I fell"}, "", proc, dl_data)
        # Find the notice_of_claim stage
        noc = next(s for s in result.stages if s.stage["id"] == "notice_of_claim")
        assert noc.deadline_date == "January 15, 2027"
        assert noc.days_remaining == 60
        assert not noc.is_expired

    def test_fallback_has_stages(self):
        proc = select_procedure("Criminal", None, False)
        result = locate_stages({}, "", proc)
        assert len(result.stages) >= 4


class TestCheckSignals:
    def test_simple_key_match(self):
        assert _check_signals(["narrative"], {"narrative": "I fell"}, "")

    def test_key_value_match(self):
        assert _check_signals(
            ["actions_taken:filed"],
            {"actions_taken": "I filed a notice"},
            ""
        )

    def test_no_match(self):
        assert not _check_signals(["narrative"], {}, "")

    def test_empty_signals_false(self):
        assert not _check_signals([], {"narrative": "test"}, "")

    def test_actions_text_match(self):
        assert _check_signals(
            ["actions_taken:demand"],
            {},
            "sent a demand letter"
        )
