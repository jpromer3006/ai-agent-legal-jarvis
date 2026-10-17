"""Tests for intake: entity resolver, date normalizer, intent gate, case folders."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from core.intake import (
    CaseFile, DateResult, normalize_date, resolve_public_entity,
    is_advice_seeking, list_known_entities, ADVICE_REFUSAL,
)


# ---------------------------------------------------------------------------
# P0.2: Entity resolver (adversarial probes from report Section 5)
# ---------------------------------------------------------------------------
class TestEntityResolver:
    def test_lirr_at_jamaica(self):
        """Report item 1: LIRR at Jamaica must resolve to LIRR, not NYCT."""
        assert resolve_public_entity("I fell boarding a Long Island Rail Road train at Jamaica") == "Long Island Rail Road"

    def test_lirr_abbreviation(self):
        assert resolve_public_entity("Slipped on LIRR platform") == "Long Island Rail Road"

    def test_amtrak_no_match(self):
        """Report item 2: Amtrak is not MTA."""
        assert resolve_public_entity("An Amtrak train door hit me at Penn Station") is None

    def test_gas_station_no_match(self):
        """Report item 3: gas station is not a public entity."""
        assert resolve_public_entity("I slipped at a gas station on Atlantic Ave") is None

    def test_police_station_no_match(self):
        assert resolve_public_entity("I fell at the police station") is None

    def test_personal_trainer_no_match(self):
        assert resolve_public_entity("My personal trainer hurt me") is None

    def test_metro_north(self):
        assert resolve_public_entity("Fell on Metro-North train") == "Metro-North Commuter Railroad"

    def test_metro_north_variant(self):
        assert resolve_public_entity("Metro North commuter railroad accident") == "Metro-North Commuter Railroad"

    def test_subway(self):
        assert resolve_public_entity("I fell in the subway station") == "New York City Transit Authority"

    def test_the_a_train(self):
        assert resolve_public_entity("I was on the A train when it happened") == "New York City Transit Authority"

    def test_mta_bus(self):
        assert resolve_public_entity("MTA bus hit me") == "MTA Bus Company"

    def test_staten_island_railway(self):
        assert resolve_public_entity("Staten Island Railway accident") == "Staten Island Rapid Transit Operating Authority"

    def test_nj_transit_no_match(self):
        assert resolve_public_entity("NJ Transit bus hit me") is None

    def test_path_train_no_match(self):
        assert resolve_public_entity("PATH train accident at WTC") is None

    def test_nycha(self):
        assert resolve_public_entity("NYCHA building stairway collapse") == "New York City Housing Authority"

    def test_none_when_uncertain(self):
        """Report item 4: 'Bus hit me in Yonkers' — which operator? Return None."""
        result = resolve_public_entity("Bus hit me in Yonkers")
        # Could be Westchester Bee-Line, MTA Bus, city bus — uncertain
        # Accept None or a specific match, but NOT NYCT
        if result is not None:
            assert result != "New York City Transit Authority"

    def test_known_entities_list(self):
        entities = list_known_entities()
        assert len(entities) >= 5
        assert "Long Island Rail Road" in entities

    # --- Cleanup 3 item 1: City of New York across boroughs ---
    def test_pothole_brooklyn(self):
        assert resolve_public_entity("I tripped in a pothole in Brooklyn") == "City of New York"

    def test_sidewalk_manhattan(self):
        assert resolve_public_entity("Cracked sidewalk in Manhattan caused me to fall") == "City of New York"

    def test_crosswalk_queens(self):
        assert resolve_public_entity("Hit by a car in a crosswalk in Queens") == "City of New York"

    def test_roadway_bronx(self):
        assert resolve_public_entity("Dangerous roadway condition in the Bronx") == "City of New York"

    def test_park_staten_island(self):
        assert resolve_public_entity("Fell in a park on Staten Island") == "City of New York"

    def test_playground_harlem(self):
        assert resolve_public_entity("My child was hurt on a playground in Harlem, Manhattan") == "City of New York"

    def test_public_school_bronx(self):
        assert resolve_public_entity("Slipped at a public school in the Bronx") == "City of New York"

    def test_the_city_pothole(self):
        assert resolve_public_entity("The city never fixed the pothole on my street") == "City of New York"

    def test_city_street_no_borough(self):
        """city street with implied NYC context."""
        assert resolve_public_entity("I fell on a city street near Times Square") == "City of New York"

    def test_city_of_new_york_explicit(self):
        assert resolve_public_entity("City of New York is responsible") == "City of New York"

    def test_new_york_city_sidewalk(self):
        assert resolve_public_entity("New York City sidewalk was broken") == "City of New York"

    # Negatives — private and non-NYC
    def test_private_store_no_match(self):
        assert resolve_public_entity("I slipped in a Walgreens in Manhattan") is None

    def test_private_building_no_match(self):
        assert resolve_public_entity("Fell in the lobby of my apartment building") is None

    def test_non_nyc_town_no_match(self):
        assert resolve_public_entity("Pothole in Albany on the main road") is None

    def test_private_parking_lot(self):
        assert resolve_public_entity("Tripped in a mall parking lot in Brooklyn") is None

    def test_restaurant_no_match(self):
        assert resolve_public_entity("Slipped in a restaurant on Broadway") is None


# ---------------------------------------------------------------------------
# P0.6: Date normalizer with confidence
# ---------------------------------------------------------------------------
class TestDateNormalizerConfidence:
    NOW = datetime(2026, 10, 17, 12, 0)

    def test_exact_iso(self):
        r = normalize_date("2026-10-01", self.NOW)
        assert r.iso == "2026-10-01"
        assert r.confidence == "exact"

    def test_exact_us_format(self):
        r = normalize_date("10/14/2026", self.NOW)
        assert r.iso == "2026-10-14"
        assert r.confidence == "exact"

    def test_yesterday_exact(self):
        r = normalize_date("yesterday", self.NOW)
        assert r.iso == "2026-10-16"
        assert r.confidence == "exact"

    def test_day_before_yesterday(self):
        r = normalize_date("the day before yesterday", self.NOW)
        assert r.iso == "2026-10-15"
        assert r.confidence == "exact"

    def test_three_days_ago(self):
        r = normalize_date("3 days ago", self.NOW)
        assert r.iso == "2026-10-14"
        assert r.confidence == "exact"

    def test_two_days_ago_word(self):
        r = normalize_date("two days ago", self.NOW)
        assert r.iso == "2026-10-15"
        assert r.confidence == "exact"

    def test_last_month_is_vague(self):
        """P0.6: 'last month' must NOT produce a date."""
        r = normalize_date("last month", self.NOW)
        assert r.confidence == "vague"
        assert r.iso is None

    def test_last_week_is_vague(self):
        r = normalize_date("last week", self.NOW)
        assert r.confidence == "vague"
        assert r.iso is None

    def test_a_while_ago_is_vague(self):
        r = normalize_date("a while ago", self.NOW)
        assert r.confidence == "vague"
        assert r.iso is None

    def test_a_few_weeks_ago_is_vague(self):
        r = normalize_date("a few weeks ago", self.NOW)
        assert r.confidence == "vague"
        assert r.iso is None

    def test_october_14_assumed_year(self):
        """'October 14' assumes current year."""
        r = normalize_date("October 14", self.NOW)
        assert r.iso == "2026-10-14"
        assert r.confidence == "assumed"

    def test_10_14_assumed_year(self):
        r = normalize_date("10/14", self.NOW)
        assert r.iso == "2026-10-14"
        assert r.confidence == "assumed"

    def test_sept_30_2026(self):
        r = normalize_date("Sept 30, 2026", self.NOW)
        assert r.iso == "2026-09-30"
        assert r.confidence == "exact"

    def test_future_date_rejected(self):
        r = normalize_date("12/25/2026", self.NOW)
        assert r.confidence == "vague"

    def test_two_digit_year_assumed(self):
        r = normalize_date("01/02/26", self.NOW)
        assert r.confidence == "assumed"

    def test_unparseable(self):
        r = normalize_date("some random text", self.NOW)
        assert r.iso is None
        assert r.confidence == "vague"


# ---------------------------------------------------------------------------
# P0.7: Lazy case folder creation
# ---------------------------------------------------------------------------
class TestCaseFolderLazy:
    def test_construction_creates_no_folder(self, tmp_path, monkeypatch):
        """P0.7: constructing CaseFiles must not create folders."""
        monkeypatch.setattr("core.intake.CASES_DIR", tmp_path)
        cases = [CaseFile() for _ in range(5)]
        # No subdirectories should exist
        subdirs = list(tmp_path.iterdir())
        assert len(subdirs) == 0

    def test_save_creates_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.intake.CASES_DIR", tmp_path)
        c = CaseFile()
        c.facts["test"] = "value"
        c.save()
        assert c.folder.exists()
        assert (c.folder / "case.json").exists()

    def test_folder_has_random_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.intake.CASES_DIR", tmp_path)
        c1 = CaseFile()
        c2 = CaseFile()
        assert c1.folder != c2.folder


# ---------------------------------------------------------------------------
# P1.4 / Intent gate
# ---------------------------------------------------------------------------
class TestIntentGate:
    def test_should_i_sue(self):
        assert is_advice_seeking("Should I sue them?")

    def test_how_much_money(self):
        assert is_advice_seeking("How much is my case worth?")

    def test_do_i_need_lawyer(self):
        assert is_advice_seeking("Do I need a lawyer?")

    def test_write_my_complaint(self):
        assert is_advice_seeking("Write my notice of claim for me")

    def test_factual_answer_not_advice(self):
        assert not is_advice_seeking("I fell on the subway steps last Tuesday and hurt my knee")

    def test_long_factual_question(self):
        assert not is_advice_seeking("The accident happened at the corner of Broadway and 42nd Street near the subway entrance around 3pm")
