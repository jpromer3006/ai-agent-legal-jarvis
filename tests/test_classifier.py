"""Tests for classifier word-boundary matching (P1.3, P1.4)."""
from core.classifier import baseline_classify


class TestClassifierWordBoundary:
    """P1.4 regression tests from the adversarial report."""

    def test_parent_will_surgery(self):
        """'My parent...I will need surgery' should NOT score Housing or Estates."""
        results = baseline_classify("My parent fell and I will need surgery")
        area_names = {r.area for r in results}
        assert "Housing / Landlord Tenant" not in area_names  # "rent" from "parent"
        assert "Estates / Probate" not in area_names  # "will" from "I will"

    def test_small_business_canada(self):
        """'small business in Canada, restraining' should NOT score Torts or Civil Rights."""
        results = baseline_classify("I run a small business in Canada and need a restraining order")
        area_names = {r.area for r in results}
        assert "Torts / Personal Injury" not in area_names  # "bus" from "business"

    def test_theater_wheelchair(self):
        """'wheelchair access at a theater' should NOT score Housing 100%."""
        results = baseline_classify("I need wheelchair access at a theater downtown")
        area_names = {r.area for r in results}
        assert "Housing / Landlord Tenant" not in area_names  # "heat" from "theater"

    def test_subway_fall_scores_torts(self):
        """Basic positive case: subway fall should score Torts."""
        results = baseline_classify("I fell on the subway steps and hurt my knee")
        assert results[0].area == "Torts / Personal Injury"

    def test_eviction_scores_housing(self):
        results = baseline_classify("My landlord is trying to evict me from my apartment")
        assert results[0].area == "Housing / Landlord Tenant"

    def test_fired_scores_employment(self):
        results = baseline_classify("I was fired from my job after complaining about harassment")
        assert results[0].area == "Employment"
