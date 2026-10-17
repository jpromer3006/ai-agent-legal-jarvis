"""Tests for authority tier classification (P1.1, P1.2)."""
from core.authority import Source, classify_url, TIER_LABELS


class TestTierClassification:
    def test_gov_is_primary(self):
        assert classify_url("https://www.nysenate.gov/legislation/laws/GMU/50-E") == 1

    def test_us_not_primary(self):
        """P1.2: .us domains are no longer auto-tier-1."""
        assert classify_url("https://example.us/something") == 5

    def test_bill_is_legislative_history(self):
        """P1.2: Senate bills are legislative history, not primary law."""
        url = "https://www.nysenate.gov/legislation/bills/2023/S1234"
        assert classify_url(url) == 6
        s = Source(url, "Senate Bill S1234")
        assert s.label == "LEGISLATIVE HISTORY"

    def test_mtaig_is_gov_non_legal(self):
        """P1.2: MTA Inspector General is government but not law."""
        url = "https://mtaig.ny.gov/some-complaint-faq"
        assert classify_url(url) == 7
        s = Source(url, "MTA IG FAQ")
        assert s.label == "GOVERNMENT, NON-LEGAL"

    def test_cornell_is_secondary(self):
        assert classify_url("https://www.law.cornell.edu/wex/negligence") == 2

    def test_reuters_is_news(self):
        assert classify_url("https://www.reuters.com/legal/article") == 3

    def test_youtube_is_community(self):
        assert classify_url("https://www.youtube.com/watch?v=123") == 4

    def test_unknown_is_unverified(self):
        assert classify_url("https://randomsite.com/page") == 5

    def test_enacted_law_on_nysenate_is_primary(self):
        """Regular /legislation/laws/ path stays T1."""
        url = "https://www.nysenate.gov/legislation/laws/GMU/50-E"
        assert classify_url(url) == 1
