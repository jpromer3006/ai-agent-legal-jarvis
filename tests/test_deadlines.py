"""Unit tests for the deadline engine and date normalizer."""
import pytest
from datetime import date, datetime

from core.deadlines import compute_deadline, load_first_steps, find_first_step
from core.intake import normalize_date


# ---------------------------------------------------------------------------
# compute_deadline
# ---------------------------------------------------------------------------
class TestComputeDeadline:
    RULE_90_DAYS = {"type": "days", "days_or_months": 90, "trigger": "incident_date"}
    RULE_6_MONTHS = {"type": "months", "days_or_months": 6, "trigger": "incident_date"}

    def test_today_incident(self):
        today = date(2026, 10, 14)
        r = compute_deadline("2026-10-14", self.RULE_90_DAYS, today=today)
        assert r.deadline_date == date(2027, 1, 12)
        assert r.days_remaining == 90
        assert not r.is_expired

    def test_89_days_ago(self):
        today = date(2026, 10, 14)
        incident = date(2026, 7, 17)  # 89 days before Oct 14
        r = compute_deadline(incident, self.RULE_90_DAYS, today=today)
        assert r.days_remaining == 1
        assert not r.is_expired

    def test_91_days_ago_expired(self):
        today = date(2026, 10, 14)
        incident = date(2026, 7, 15)  # 91 days before Oct 14
        r = compute_deadline(incident, self.RULE_90_DAYS, today=today)
        assert r.days_remaining == -1
        assert r.is_expired

    def test_leap_year(self):
        # 2028 is a leap year; incident on Jan 1, deadline 90 days = Mar 31
        today = date(2028, 1, 1)
        r = compute_deadline("2028-01-01", self.RULE_90_DAYS, today=today)
        assert r.deadline_date == date(2028, 3, 31)  # 31+29+31-1 = 90 days
        assert r.days_remaining == 90

    def test_months_rule(self):
        r = compute_deadline("2026-10-14", self.RULE_6_MONTHS, today=date(2026, 10, 14))
        assert r.deadline_date == date(2027, 4, 14)

    def test_months_clamp_end_of_month(self):
        # Jan 31 + 1 month should be Feb 28 (non-leap), before rollover
        r = compute_deadline("2026-01-31", {"type": "months", "days_or_months": 1,
                             "trigger": "incident_date"}, today=date(2026, 1, 31),
                             apply_rollover=False)
        assert r.deadline_date == date(2026, 2, 28)

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            compute_deadline("not-a-date", self.RULE_90_DAYS)

    def test_invalid_rule_type_raises(self):
        with pytest.raises(ValueError):
            compute_deadline("2026-10-14", {"type": "weeks", "days_or_months": 2,
                             "trigger": "incident_date"})

    def test_label(self):
        r = compute_deadline("2026-10-14", self.RULE_90_DAYS, today=date(2026, 10, 14))
        assert "90 days" in r.label

    # Cleanup 3 item 4: weekend and holiday rollover
    def test_saturday_rolls_to_monday(self):
        # 2026-07-20 + 90 days = 2026-10-18 (Sunday) → 2026-10-19 (Monday)
        r = compute_deadline("2026-07-20", self.RULE_90_DAYS, today=date(2026, 7, 20))
        assert r.deadline_date.weekday() < 5  # weekday
        assert r.rolled_from is not None

    def test_sunday_rolls_to_monday(self):
        # 2026-07-19 + 90 days = 2026-10-17 (Saturday) → 2026-10-19 (Monday)
        r = compute_deadline("2026-07-19", self.RULE_90_DAYS, today=date(2026, 7, 19))
        assert r.deadline_date.weekday() < 5
        assert r.rolled_from is not None

    def test_holiday_rolls_forward(self):
        # If deadline lands on 2026-12-25 (Christmas, Friday), roll to 2026-12-28 (Monday)
        # Need to find an incident date where + 90 days = Dec 25
        # Sep 26 + 90 = Dec 25, 2026 (Friday)
        r = compute_deadline("2026-09-26", self.RULE_90_DAYS, today=date(2026, 9, 26))
        assert r.deadline_date != date(2026, 12, 25)
        assert r.rolled_from == date(2026, 12, 25)

    def test_weekday_no_rollover(self):
        # 2026-10-01 + 90 days = 2026-12-30 (Wednesday) — no rollover
        r = compute_deadline("2026-10-01", self.RULE_90_DAYS, today=date(2026, 10, 1))
        assert r.deadline_date == date(2026, 12, 30)
        assert r.rolled_from is None

    def test_new_years_2027_rolls(self):
        # 2027-01-01 is a holiday (Friday in 2027? Let's check)
        # Oct 3 2026 + 90 = Jan 1 2027
        r = compute_deadline("2026-10-03", self.RULE_90_DAYS, today=date(2026, 10, 3))
        assert r.deadline_date != date(2027, 1, 1)
        assert r.rolled_from == date(2027, 1, 1)

    def test_rollover_disabled(self):
        r = compute_deadline("2026-07-20", self.RULE_90_DAYS,
                             today=date(2026, 7, 20), apply_rollover=False)
        assert r.rolled_from is None


# ---------------------------------------------------------------------------
# normalize_date
# ---------------------------------------------------------------------------
class TestNormalizeDate:
    """Updated for DateResult return type (P0.6)."""

    def test_today(self):
        now = datetime(2026, 10, 14, 14, 30)
        r = normalize_date("today at 2:30 pm", now=now)
        assert r.iso == "2026-10-14"
        assert r.raw == "today at 2:30 pm"

    def test_yesterday(self):
        now = datetime(2026, 10, 14)
        r = normalize_date("yesterday", now=now)
        assert r.iso == "2026-10-13"

    def test_n_days_ago(self):
        now = datetime(2026, 10, 14)
        r = normalize_date("3 days ago", now=now)
        assert r.iso == "2026-10-11"

    def test_explicit_date(self):
        r = normalize_date("2026-10-01")
        assert r.iso == "2026-10-01"

    def test_us_format(self):
        r = normalize_date("10/14/2026")
        assert r.iso == "2026-10-14"

    def test_unparseable_returns_none(self):
        r = normalize_date("some random text")
        assert r.iso is None
        assert r.raw == "some random text"

    def test_raw_preserved(self):
        r = normalize_date("  today at 2:30 pm  ")
        assert r.raw == "  today at 2:30 pm  "


# ---------------------------------------------------------------------------
# first_steps.json
# ---------------------------------------------------------------------------
class TestFirstSteps:
    def test_load(self):
        steps = load_first_steps()
        assert len(steps) >= 1

    def test_find_nyct(self):
        s = find_first_step("Torts / Personal Injury", "New York City Transit Authority")
        assert s is not None
        assert s["id"] == "tort-nyct-notice-of-claim"
        assert s["needs_verification"] is True
        assert len(s["plain_language_steps"]) <= 5

    def test_find_missing(self):
        assert find_first_step("Imaginary Law", "Nobody") is None
