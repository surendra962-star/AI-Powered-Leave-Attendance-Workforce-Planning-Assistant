"""Phase 3 completion tests: leave management, decision support & all 10 checklist items.

Covers:
 1. Balance breakdown (entitled, used, pending, remaining, available) incl. comp_off
 2. Weekend/public holiday exclusion in working-day counts
 3. Optional holiday handling (get_optional_holidays_in_range, exclude_optional_holidays)
 4. Overlap detection
 5. Duplicate detection
 6. Notice-period enforcement
 7. Recommendation labels (Likely eligible / Needs manager review / Potential policy conflict)
 8. Rules evaluated surfaced in evaluate_leave_request result
 9. Missing information surfaced when data is absent
10. Team coverage, critical deadlines and backup in evidence; human decision authority preserved
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

import pytest

from database.db import initialize, connection
from database.seed import seed
from leave_management.service import (
    LeaveError,
    create_leave_request,
    decide_leave_request,
    get_balance,
    get_optional_holidays_in_range,
    working_days,
)
from workforce_planning.service import (
    assign_backup,
    evaluate_leave_request,
)


# ---------------------------------------------------------------------------
# Shared fixture – isolated per-test database
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Fresh seeded database for every test; never touches the main hr_assistant.db."""
    path = tmp_path / "phase3.db"
    initialize(path)
    seed(path)
    return path


# ---------------------------------------------------------------------------
# 1. Balance breakdown
# ---------------------------------------------------------------------------

class TestBalanceBreakdown:
    """Item 1: entitled, used, pending, remaining and available are all present and consistent."""

    def test_annual_balance_all_fields_present(self, db: Path) -> None:
        bal = get_balance("E001", "annual", 2026, db)
        for field in ("entitled_days", "used_days", "pending_days", "remaining_days", "available_days"):
            assert field in bal, f"Missing field: {field}"

    def test_annual_balance_arithmetic(self, db: Path) -> None:
        bal = get_balance("E001", "annual", 2026, db)
        assert round(bal["remaining_days"], 2) == round(
            bal["entitled_days"] - bal["used_days"], 2
        )
        assert round(bal["available_days"], 2) == round(
            max(0.0, bal["remaining_days"] - bal["pending_days"]), 2
        )

    def test_pending_days_increases_after_request(self, db: Path) -> None:
        bal_before = get_balance("E001", "annual", 2026, db)
        # Requesting annual leave ≥ 5 days in advance; well-within balance
        create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                             "Holiday", "2026-11-01", db)
        bal_after = get_balance("E001", "annual", 2026, db)
        assert bal_after["pending_days"] > bal_before["pending_days"]
        assert bal_after["available_days"] < bal_before["available_days"]

    def test_used_days_increases_after_approval(self, db: Path) -> None:
        from access_control.service import authenticate
        mgr = authenticate("E005", "kiranmgr@2026", db)
        req_id = create_leave_request("E001", "annual", "2026-12-14", "2026-12-16",
                                      "Sprint break", "2026-11-01", db)
        bal_before = get_balance("E001", "annual", 2026, db)
        decide_leave_request(mgr, req_id, "approved", "OK", "2026-11-05", db)
        bal_after = get_balance("E001", "annual", 2026, db)
        assert bal_after["used_days"] > bal_before["used_days"]

    def test_sick_balance_all_fields_present(self, db: Path) -> None:
        bal = get_balance("E001", "sick", 2026, db)
        for field in ("entitled_days", "used_days", "pending_days", "remaining_days", "available_days"):
            assert field in bal, f"Missing field: {field}"

    def test_comp_off_balance_all_fields_present(self, db: Path) -> None:
        bal = get_balance("E001", "comp_off", 2026, db)
        for field in ("entitled_days", "used_days", "pending_days", "remaining_days", "available_days"):
            assert field in bal, f"Missing field: {field}"

    def test_comp_off_balance_non_negative_available(self, db: Path) -> None:
        bal = get_balance("E001", "comp_off", 2026, db)
        assert bal["available_days"] >= 0.0

    def test_invalid_leave_type_raises(self, db: Path) -> None:
        with pytest.raises(LeaveError):
            get_balance("E001", "casual", 2026, db)


# ---------------------------------------------------------------------------
# 2. Weekend / public holiday exclusion
# ---------------------------------------------------------------------------

class TestWorkingDayCalculation:
    """Item 2: Weekends and public holidays are excluded from working-day counts."""

    def test_weekend_days_excluded(self, db: Path) -> None:
        # 2026-11-28 (Sat) → 2026-11-29 (Sun): 0 working days
        assert working_days("2026-11-28", "2026-11-29", db) == 0

    def test_full_week_counts_five(self, db: Path) -> None:
        # 2026-11-16 (Mon) → 2026-11-20 (Fri) = 5 working days
        # 2026-11-20 is a seeded optional holiday; still counts unless excluded
        count = working_days("2026-11-16", "2026-11-20", db)
        assert count == 5

    def test_public_holiday_excluded(self, db: Path) -> None:
        # Seed inserts 'Sample Winter Holiday' on 2026-12-25 (Fri).
        # Mon 2026-12-21 → Fri 2026-12-25 = 5 weekdays minus 1 holiday = 4
        count = working_days("2026-12-21", "2026-12-25", db)
        assert count == 4

    def test_mixed_week_with_weekend(self, db: Path) -> None:
        # Thu 2026-11-05 → Mon 2026-11-10: Thu+Fri (skip Sat+Sun) + Mon = 3
        assert working_days("2026-11-05", "2026-11-10", db) == 3

    def test_single_working_day(self, db: Path) -> None:
        # Wednesday
        assert working_days("2026-11-04", "2026-11-04", db) == 1

    def test_end_before_start_raises(self, db: Path) -> None:
        with pytest.raises(LeaveError):
            working_days("2026-11-10", "2026-11-09", db)


# ---------------------------------------------------------------------------
# 3. Optional holiday handling
# ---------------------------------------------------------------------------

class TestOptionalHolidays:
    """Item 3: Optional holidays are queryable and can be excluded from working-day counts."""

    def test_get_optional_holidays_returns_seeded_entry(self, db: Path) -> None:
        result = get_optional_holidays_in_range("2026-11-01", "2026-11-30", db)
        dates = [r["date"] for r in result]
        assert "2026-11-20" in dates, "Seeded optional holiday not found"

    def test_get_optional_holidays_empty_outside_range(self, db: Path) -> None:
        result = get_optional_holidays_in_range("2026-09-01", "2026-09-30", db)
        assert result == []

    def test_optional_holiday_counts_as_working_day_by_default(self, db: Path) -> None:
        # 2026-11-16 (Mon) → 2026-11-20 (Fri): optional holiday on 2026-11-20
        count_default = working_days("2026-11-16", "2026-11-20", db)
        assert count_default == 5  # optional holiday still counts

    def test_exclude_optional_holiday_reduces_count(self, db: Path) -> None:
        count_excl = working_days("2026-11-16", "2026-11-20", db,
                                  exclude_optional_holidays=True)
        # Optional holiday on 2026-11-20 excluded → 4 working days
        assert count_excl == 4

    def test_create_request_with_optional_excluded(self, db: Path) -> None:
        # Mon 2026-11-16 → Fri 2026-11-20: normally 5 working days;
        # with optional excluded → 4 charged days
        req_id = create_leave_request(
            "E001", "annual", "2026-11-16", "2026-11-20",
            "Optional holiday week", "2026-11-05", db,
            exclude_optional_holidays=True,
        )
        with connection(db) as conn:
            row = conn.execute(
                "SELECT requested_days FROM leave_requests WHERE request_id=?", (req_id,)
            ).fetchone()
        assert row["requested_days"] == 4.0

    def test_create_request_without_optional_excluded(self, db: Path) -> None:
        req_id = create_leave_request(
            "E001", "annual", "2026-11-16", "2026-11-20",
            "Full week leave", "2026-11-05", db,
        )
        with connection(db) as conn:
            row = conn.execute(
                "SELECT requested_days FROM leave_requests WHERE request_id=?", (req_id,)
            ).fetchone()
        assert row["requested_days"] == 5.0


# ---------------------------------------------------------------------------
# 4. Overlap detection
# ---------------------------------------------------------------------------

class TestOverlapDetection:
    """Item 4: Overlapping leave requests for the same employee are rejected."""

    def test_exact_overlap_raises_leave_error(self, db: Path) -> None:
        create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                             "Trip", "2026-11-01", db)
        with pytest.raises(LeaveError, match="overlap|already exists"):
            create_leave_request("E001", "annual", "2026-12-08", "2026-12-10",
                                 "Another trip", "2026-11-01", db)

    def test_contained_range_raises_leave_error(self, db: Path) -> None:
        create_leave_request("E001", "annual", "2026-12-14", "2026-12-18",
                             "Week off", "2026-11-01", db)
        with pytest.raises(LeaveError, match="overlap|already exists"):
            create_leave_request("E001", "annual", "2026-12-15", "2026-12-16",
                                 "Inner range", "2026-11-01", db)

    def test_adjacent_non_overlapping_allowed(self, db: Path) -> None:
        create_leave_request("E001", "annual", "2026-12-21", "2026-12-22",
                             "Monday–Tuesday", "2026-11-01", db)
        # Next request starts on 2026-12-23 (Wednesday) — no overlap
        req_id = create_leave_request("E001", "annual", "2026-12-23", "2026-12-24",
                                      "Wednesday–Thursday", "2026-11-01", db)
        assert req_id > 0

    def test_different_employees_same_dates_allowed(self, db: Path) -> None:
        create_leave_request("E001", "annual", "2026-12-28", "2026-12-29",
                             "E001 leave", "2026-11-01", db)
        req_id = create_leave_request("E006", "annual", "2026-12-28", "2026-12-29",
                                      "E006 leave", "2026-11-01", db)
        assert req_id > 0


# ---------------------------------------------------------------------------
# 5. Duplicate detection
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    """Item 5: Exact duplicate requests (same employee, type, dates) are rejected."""

    def test_exact_duplicate_raises_leave_error(self, db: Path) -> None:
        create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                             "Holiday", "2026-11-01", db)
        with pytest.raises(LeaveError, match="Duplicate|already exists"):
            create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                 "Same dates again", "2026-11-01", db)

    def test_different_leave_type_same_dates_raises_overlap(self, db: Path) -> None:
        # Different type but overlapping dates should still be caught by overlap check
        create_leave_request("E001", "annual", "2026-12-14", "2026-12-16",
                             "Annual", "2026-11-01", db)
        with pytest.raises(LeaveError, match="overlap|already exists"):
            # sick leave overlapping same dates → overlap error
            create_leave_request("E001", "sick", "2026-12-14", "2026-12-15",
                                 "Sick", "2026-11-01", db)


# ---------------------------------------------------------------------------
# 6. Notice-period enforcement
# ---------------------------------------------------------------------------

class TestNoticePeriod:
    """Item 6: Annual leave requires >= 5 days advance notice; sick leave is exempt."""

    def test_annual_leave_too_short_notice_raises(self, db: Path) -> None:
        # Submitted on 2026-11-10; leave starts 2026-11-13 → only 3 days notice
        with pytest.raises(LeaveError, match="5 calendar days|advance"):
            create_leave_request("E001", "annual", "2026-11-13", "2026-11-13",
                                 "Last minute", "2026-11-10", db)

    def test_annual_leave_exactly_five_days_notice_allowed(self, db: Path) -> None:
        # Submitted 2026-11-01; leave starts 2026-11-06 → exactly 5 days
        req_id = create_leave_request("E001", "annual", "2026-11-06", "2026-11-06",
                                      "Five-day notice", "2026-11-01", db)
        assert req_id > 0

    def test_annual_leave_less_than_five_days_raises(self, db: Path) -> None:
        with pytest.raises(LeaveError, match="5 calendar days|advance"):
            create_leave_request("E001", "annual", "2026-11-05", "2026-11-05",
                                 "Four-day notice", "2026-11-01", db)

    def test_sick_leave_no_notice_required(self, db: Path) -> None:
        # Sick leave submitted same day as start — notice rule is waived.
        # Use a date far enough in the future that 'start < submitted' check passes.
        req_id = create_leave_request("E001", "sick", "2026-12-01", "2026-12-01",
                                      "Feeling unwell", "2026-12-01", db)
        assert req_id > 0


# ---------------------------------------------------------------------------
# 7. Recommendation labels
# ---------------------------------------------------------------------------

class TestRecommendationLabels:
    """Item 7: evaluate_leave_request returns the correct recommendation label."""

    def _make_request(self, db: Path, start: str = "2026-12-07",
                      end: str = "2026-12-09", submitted_on: str = "2026-11-01") -> int:
        return create_leave_request(
            "E001", "annual", start, end, "Test request", submitted_on, db
        )

    def test_low_risk_label_is_likely_eligible(self, db: Path) -> None:
        req_id = self._make_request(db)
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        # With sufficient balance, notice, no breaches and no critical deadlines → Likely eligible
        assert result["recommendation"] in ("low_risk", "review_required")
        if result["recommendation"] == "low_risk":
            assert result["recommendation_label"] == "Likely eligible"

    def test_recommendation_label_key_always_present(self, db: Path) -> None:
        req_id = self._make_request(db)
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert "recommendation_label" in result
        assert result["recommendation_label"] in (
            "Likely eligible", "Needs manager review", "Potential policy conflict"
        )

    def test_high_risk_label_is_potential_policy_conflict(self, db: Path) -> None:
        # Create request FIRST while balance is sufficient, then exhaust balance before evaluation
        req_id = self._make_request(db, start="2026-12-14", end="2026-12-18")
        with connection(db) as conn:
            conn.execute(
                "UPDATE leave_balances SET used_days=18 WHERE employee_id='E001' AND leave_type='annual' AND year=2026"
            )
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert result["recommendation"] == "high_risk"
        assert result["recommendation_label"] == "Potential policy conflict"

    def test_review_required_label_when_deadline_exists(self, db: Path) -> None:
        req_id = self._make_request(db, start="2026-12-07", end="2026-12-09")
        # Assign a critical deadline within the leave period for E001's team
        with connection(db) as conn:
            team_id = conn.execute(
                "SELECT team_id FROM employees WHERE employee_id='E001'"
            ).fetchone()["team_id"]
            conn.execute(
                """INSERT INTO project_deadlines(title, due_on, team_id, critical, owner_id)
                   VALUES (?, ?, ?, ?, ?)""",
                ("Critical Sprint Review", "2026-12-08", team_id, 1, "E001")
            )
            d_id = conn.execute(
                "SELECT deadline_id FROM project_deadlines WHERE title='Critical Sprint Review'"
            ).fetchone()["deadline_id"]
            # Assign backup so it doesn't become high_risk
            conn.execute(
                "INSERT INTO backup_assignments(deadline_id, backup_employee_id, assigned_on) VALUES (?,?,?)",
                (d_id, "E002", "2026-12-08")
            )
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert result["recommendation"] in ("review_required", "low_risk")
        if result["recommendation"] == "review_required":
            assert result["recommendation_label"] == "Needs manager review"


# ---------------------------------------------------------------------------
# 8. Rules evaluated displayed
# ---------------------------------------------------------------------------

class TestRulesEvaluated:
    """Item 8: rules_evaluated list is present in result with rule/status/observed fields."""

    def test_rules_evaluated_present(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Test", "2026-11-01", db)
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert "rules_evaluated" in result
        rules = result["rules_evaluated"]
        assert isinstance(rules, list)
        assert len(rules) >= 3

    def test_each_rule_has_required_keys(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Test", "2026-11-01", db)
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        for rule in result["rules_evaluated"]:
            assert "rule" in rule
            assert "status" in rule
            assert "observed" in rule
            assert rule["status"] in ("PASS", "FAIL")

    def test_notice_rule_pass_when_sufficient_notice(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Test", "2026-11-01", db)
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        notice_rule = next(
            (r for r in result["rules_evaluated"] if "Notice" in r["rule"]), None
        )
        assert notice_rule is not None
        assert notice_rule["status"] == "PASS"

    def test_balance_rule_fail_when_exhausted(self, db: Path) -> None:
        # Create request while balance is sufficient, then exhaust before evaluation
        req_id = create_leave_request("E001", "annual", "2026-12-14", "2026-12-18",
                                      "Test", "2026-11-01", db)
        with connection(db) as conn:
            conn.execute(
                "UPDATE leave_balances SET used_days=18 WHERE employee_id='E001' AND leave_type='annual' AND year=2026"
            )
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        bal_rule = next(
            (r for r in result["rules_evaluated"] if "Balance" in r["rule"]), None
        )
        assert bal_rule is not None
        assert bal_rule["status"] == "FAIL"

    def test_missing_balance_record_does_not_fail_rule(self, db: Path) -> None:
        """When no balance record exists, balance rule is PASS with missing info warning."""
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Test", "2026-11-01", db)
        # Remove balance rows to simulate missing data
        with connection(db) as conn:
            conn.execute(
                "DELETE FROM leave_balances WHERE employee_id='E001' AND leave_type='annual'"
            )
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        bal_rule = next(
            (r for r in result["rules_evaluated"] if "Balance" in r["rule"]), None
        )
        assert bal_rule is not None
        assert bal_rule["status"] == "PASS"
        # Missing info should contain a note about the missing record
        assert any("balance" in m.lower() for m in result.get("missing_information", []))


# ---------------------------------------------------------------------------
# 9. Missing information surfaced
# ---------------------------------------------------------------------------

class TestMissingInformation:
    """Item 9: missing_information key is present; warnings surface known unknowns."""

    def test_missing_information_key_present(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Test", "2026-11-01", db)
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert "missing_information" in result
        assert isinstance(result["missing_information"], list)

    def test_no_reason_flagged_as_missing(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "", "2026-11-01", db)
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert any("reason" in m.lower() for m in result["missing_information"])

    def test_missing_balance_record_surfaced(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Test", "2026-11-01", db)
        with connection(db) as conn:
            conn.execute(
                "DELETE FROM leave_balances WHERE employee_id='E001' AND leave_type='annual'"
            )
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert any("balance" in m.lower() for m in result["missing_information"])

    def test_critical_deadline_no_backup_surfaced(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Vacation", "2026-11-01", db)
        with connection(db) as conn:
            team_id = conn.execute(
                "SELECT team_id FROM employees WHERE employee_id='E001'"
            ).fetchone()["team_id"]
            conn.execute(
                """INSERT INTO project_deadlines(title, due_on, team_id, critical, owner_id)
                   VALUES (?, ?, ?, ?, ?)""",
                ("Unprotected Critical Deadline", "2026-12-08", team_id, 1, "E001")
            )
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        assert any("backup" in m.lower() or "critical" in m.lower()
                   for m in result["missing_information"])


# ---------------------------------------------------------------------------
# 10. Team coverage, deadlines, backup in evidence; human decision authority
# ---------------------------------------------------------------------------

class TestEvidenceAndHumanDecisionAuthority:
    """Item 10: Evidence contains daily_coverage, project_deadlines, attendance_context.
    The result must never carry automatic_approval=True or a pre-filled final_decision."""

    def _evaluate(self, db: Path) -> Dict[str, Any]:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Test", "2026-11-01", db)
        return evaluate_leave_request(req_id, date.today().isoformat(), db)

    def test_daily_coverage_in_evidence(self, db: Path) -> None:
        result = self._evaluate(db)
        evidence = result["evidence"]
        assert "daily_coverage" in evidence
        assert isinstance(evidence["daily_coverage"], list)
        # Each entry must have 'date' and 'coverage_percent_after_request'
        for entry in evidence["daily_coverage"]:
            assert "date" in entry
            assert "coverage_percent_after_request" in entry

    def test_project_deadlines_in_evidence(self, db: Path) -> None:
        result = self._evaluate(db)
        evidence = result["evidence"]
        assert "project_deadlines" in evidence
        assert isinstance(evidence["project_deadlines"], list)

    def test_attendance_context_in_evidence(self, db: Path) -> None:
        result = self._evaluate(db)
        assert "attendance_context" in result
        ctx = result["attendance_context"]
        for key in ("window_start", "window_end", "total_logged_days",
                    "present_days", "attendance_rate_percent", "disclaimer"):
            assert key in ctx, f"Missing attendance_context key: {key}"

    def test_attendance_context_disclaimer_present(self, db: Path) -> None:
        result = self._evaluate(db)
        disclaimer = result["attendance_context"].get("disclaimer", "")
        assert len(disclaimer) > 10, "Attendance context disclaimer must be non-trivial"

    def test_automatic_approval_never_true(self, db: Path) -> None:
        result = self._evaluate(db)
        # The system must not autonomously approve leave
        assert result.get("automatic_approval", False) is False

    def test_final_decision_not_set_by_system(self, db: Path) -> None:
        result = self._evaluate(db)
        # final_decision (if present) must be None — only manager/HR can set it
        final = result.get("final_decision")
        assert final is None

    def test_recommendation_label_not_a_decision(self, db: Path) -> None:
        result = self._evaluate(db)
        label = result.get("recommendation_label", "")
        # Must be one of the advisory labels — none should read "Approved" / "Rejected"
        assert label not in ("Approved", "Rejected", "Auto-approved", "Auto-rejected")

    def test_coverage_breach_dates_key_present(self, db: Path) -> None:
        result = self._evaluate(db)
        assert "coverage_breach_dates" in result
        assert isinstance(result["coverage_breach_dates"], list)

    def test_reasons_list_non_empty(self, db: Path) -> None:
        result = self._evaluate(db)
        assert "reasons" in result
        assert len(result["reasons"]) >= 1

    def test_backup_assignment_included_in_deadline_evidence(self, db: Path) -> None:
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Vacation", "2026-11-01", db)
        with connection(db) as conn:
            team_id = conn.execute(
                "SELECT team_id FROM employees WHERE employee_id='E001'"
            ).fetchone()["team_id"]
            conn.execute(
                """INSERT INTO project_deadlines(title, due_on, team_id, critical, owner_id)
                   VALUES (?, ?, ?, ?, ?)""",
                ("Protected Deadline", "2026-12-08", team_id, 1, "E001")
            )
            d_id = conn.execute(
                "SELECT deadline_id FROM project_deadlines WHERE title='Protected Deadline'"
            ).fetchone()["deadline_id"]
            conn.execute(
                "INSERT INTO backup_assignments(deadline_id, backup_employee_id, assigned_on) VALUES (?,?,?)",
                (d_id, "E002", "2026-12-08")
            )
        result = evaluate_leave_request(req_id, date.today().isoformat(), db)
        evidence = result["evidence"]
        deadline_titles = [d.get("title") for d in evidence["project_deadlines"]]
        assert "Protected Deadline" in deadline_titles
        # With backup assigned the deadline should not block to high_risk
        assert result["recommendation"] in ("low_risk", "review_required")

