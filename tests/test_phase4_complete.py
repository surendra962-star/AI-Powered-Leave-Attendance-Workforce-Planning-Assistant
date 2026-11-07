"""Comprehensive Phase 4 tests: Attendance, Comp-Off & Workforce Planning.

Covers all 15 required checklist items:
Attendance:
 1. Verify duplicate clock-in prevention.
 2. Handle missing clock-outs.
 3. Generate accurate monthly attendance summaries.

Comp-off and holidays:
 4. Track earned, approved, used and remaining comp-off.
 5. Track expiry dates.
 6. Prevent duplicate use of the same comp-off record.
 7. Flag expired or invalid records.
 8. Display public holidays, optional holidays and working days in a calendar or list.
 9. Explain how a leave request interacts with holidays and comp-off.

Workforce and timelines:
10. Track leave start/end dates, submission dates and expected return dates.
11. Track notice deadlines and approval due dates.
12. Track comp-off expiry and project deadlines.
13. Show upcoming events and overdue alerts.
14. Detect low coverage and missing backup assignments.
15. Allow timeline questions such as deadlines overlapping a proposed leave period.
"""
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Any

import pytest

from database.db import initialize, connection
from database.seed import seed
from access_control.service import UserContext, authenticate, initialize_security
from attendance.service import (
    clock_in, clock_out, record_attendance,
    get_employee_attendance, get_team_attendance,
    get_monthly_attendance_summary, get_missing_clock_outs,
    regularize_missing_clock_out, AttendanceError
)
from leave_management.service import (
    create_leave_request, decide_leave_request, cancel_leave_request,
    list_holidays, get_calendar_breakdown, explain_leave_interaction,
    refresh_comp_off_status, LeaveError
)
from timeline.service import (
    comp_off_summary, record_comp_off, get_alerts, list_timeline,
    calculate_return_to_work_date, query_timeline_overlap
)
from workforce_planning.service import (
    evaluate_leave_request, assign_backup, team_capacity_forecast, list_team_deadlines
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Isolated, seeded test database."""
    path = tmp_path / "phase4_assessment.db"
    initialize(path)
    seed(path)
    initialize_security(path)
    return path


# ==============================================================================
# SECTION A: ATTENDANCE MANAGEMENT (Items 1 - 3)
# ==============================================================================

class TestAttendanceManagement:
    """Items 1, 2, 3: Clock-in duplicate checks, missing clock-outs, monthly summaries."""

    def test_duplicate_clock_in_prevention(self, db: Path) -> None:
        """Item 1: Verify duplicate clock-in on the same date is rejected."""
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")
        target_date = "2026-11-12"

        # First clock-in succeeds
        res1 = clock_in(emp, "E001", att_date=target_date, time_str="09:05:00", db_path=db)
        assert res1["status"] == "present"
        assert res1["check_in"] == "09:05:00"

        # Second clock-in on the exact same day raises AttendanceError
        with pytest.raises(AttendanceError, match="Duplicate clock-in prevented"):
            clock_in(emp, "E001", att_date=target_date, time_str="09:30:00", db_path=db)

    def test_clock_out_requires_prior_clock_in(self, db: Path) -> None:
        """Item 2: Clock-out without prior clock-in raises AttendanceError unless bypassed."""
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")
        target_date = "2026-11-13"

        # Attempt to clock out without clocking in first
        with pytest.raises(AttendanceError, match="No prior clock-in record found"):
            clock_out(emp, "E001", att_date=target_date, time_str="18:00:00", db_path=db)

        # Explicit bypass works if configured
        bypassed = clock_out(emp, "E001", att_date=target_date, time_str="18:00:00",
                             allow_missing_check_in=True, db_path=db)
        assert bypassed["check_out"] == "18:00:00"

    def test_missing_clock_out_detection_and_regularization(self, db: Path) -> None:
        """Item 2: Incomplete attendance records (clocked in, no clock-out) are identified and regularized."""
        mgr = UserContext("E005", "Kiran Rao", "manager", "T01")
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")
        target_date = "2026-11-14"

        # Rahul clocks in at 09:15, but forgets to clock out
        clock_in(emp, "E001", att_date=target_date, time_str="09:15:00", db_path=db)

        # Manager inspects missing clock-outs
        missing = get_missing_clock_outs(mgr, before_date=target_date, employee_id="E001", db_path=db)
        assert len(missing) >= 1
        found = next((m for m in missing if m["date"] == target_date and m["employee_id"] == "E001"), None)
        assert found is not None
        assert found["check_in"] == "09:15:00"
        assert found["check_out"] is None

        # Manager regularizes the record
        reg = regularize_missing_clock_out(
            mgr, "E001", target_date, default_check_out="17:30:00",
            note="Approved overtime punch-out", db_path=db
        )
        assert reg["check_out"] == "17:30:00"
        assert reg["regularized_by"] == "E005"

        # Now no missing clock-out remains for that day
        missing_after = get_missing_clock_outs(mgr, before_date=target_date, employee_id="E001", db_path=db)
        assert not any(m["date"] == target_date for m in missing_after)

    def test_accurate_monthly_attendance_summary(self, db: Path) -> None:
        """Item 3: Monthly summary computes present, absent, approved_leave, missing_outs, and percentage."""
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")
        month = "2026-10"

        # Clear pre-seeded attendance for E001 in October 2026 for exact test control
        with connection(db) as conn:
            conn.execute("DELETE FROM attendance WHERE employee_id='E001' AND substr(date, 1, 7)='2026-10'")

        # Record 4 present days with clock-in/out, 1 present day missing clock-out, 1 absent, 1 approved leave
        record_attendance(emp, "E001", "2026-10-05", "present", check_in="09:00:00", check_out="17:00:00", db_path=db)
        record_attendance(emp, "E001", "2026-10-06", "present", check_in="09:00:00", check_out="17:00:00", db_path=db)
        record_attendance(emp, "E001", "2026-10-07", "present", check_in="09:00:00", check_out="17:00:00", db_path=db)
        record_attendance(emp, "E001", "2026-10-08", "present", check_in="09:00:00", check_out="17:00:00", db_path=db)
        # Missing clock out:
        record_attendance(emp, "E001", "2026-10-09", "present", check_in="09:00:00", check_out=None, db_path=db)
        # Absent day:
        record_attendance(emp, "E001", "2026-10-12", "absent", db_path=db)
        # Approved leave day:
        record_attendance(emp, "E001", "2026-10-13", "approved_leave", db_path=db)

        summary = get_monthly_attendance_summary(emp, month, employee_id="E001", db_path=db)
        assert summary["month"] == "2026-10"
        assert summary["present_days"] == 5
        assert summary["absent_days"] == 1
        assert summary["approved_leave_days"] == 1
        assert summary["missing_clock_outs"] == 1
        assert summary["working_days_in_month"] >= 20
        assert summary["unrecorded_days"] >= 10
        # Formula: present / (present + absent) * 100 => 5 / (5 + 1) * 100 = 83.33%
        assert summary["attendance_percentage"] == round((5 / 6) * 100, 2)


# ==============================================================================
# SECTION B: COMP-OFF & HOLIDAYS (Items 4 - 9)
# ==============================================================================

class TestCompOffAndHolidays:
    """Items 4, 5, 6, 7, 8, 9: Comp-off tracking, expiry, duplicate prevention, holiday breakdown, explanations."""

    def test_comp_off_earned_used_remaining_and_available(self, db: Path) -> None:
        """Item 4: Comp-off summary tracks earned, used, remaining and available days."""
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")
        summary = comp_off_summary(emp, "E001", as_of="2026-11-01", db_path=db)

        for k in ("earned_days", "used_days", "available_days", "remaining_days", "pending_days", "expired_days"):
            assert k in summary, f"Key {k} missing from comp_off_summary"

        assert summary["earned_days"] >= summary["available_days"]
        assert summary["available_days"] >= summary["remaining_days"]

    def test_comp_off_expiry_dates_and_flags(self, db: Path) -> None:
        """Item 5 & 7: Tracks expiry dates, days to expiry, and flags expired or valid records."""
        mgr = UserContext("E005", "Kiran Rao", "manager", "T01")
        # Grant a comp-off expiring in 10 days
        cid_expiring = record_comp_off(
            mgr, "E001", "2026-11-01", "2026-11-15", days=1.0, db_path=db, work_reference="Weekend bug fix"
        )
        assert cid_expiring > 0

        # As of Nov 5: 10 days left -> is_valid=True, is_expiring_soon=True, is_expired=False
        summary = comp_off_summary(mgr, "E001", as_of="2026-11-05", db_path=db)
        rec = next(r for r in summary["records"] if r["comp_off_id"] == cid_expiring)
        assert rec["is_valid"] is True
        assert rec["is_expired"] is False
        assert rec["is_expiring_soon"] is True
        assert rec["days_to_expiry"] == 10

        # As of Nov 20: expired -> is_expired=True, is_valid=False
        summary_after = comp_off_summary(mgr, "E001", as_of="2026-11-20", db_path=db)
        rec_after = next(r for r in summary_after["records"] if r["comp_off_id"] == cid_expiring)
        assert rec_after["is_expired"] is True
        assert rec_after["is_valid"] is False

    def test_prevent_duplicate_use_of_same_comp_off_record(self, db: Path) -> None:
        """Item 6: Prevent double-booking / duplicate pending requests using the same comp-off days."""
        mgr = UserContext("E005", "Kiran Rao", "manager", "T01")
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")

        # Give employee exactly 1.0 day of fresh comp-off
        with connection(db) as conn:
            conn.execute("DELETE FROM comp_off_records WHERE employee_id='E001'")
            conn.execute("DELETE FROM leave_requests WHERE employee_id='E001' AND leave_type='comp_off'")

        record_comp_off(mgr, "E001", "2026-11-01", "2026-12-31", days=1.0, db_path=db, work_reference="Sprint overtime")

        # First request consumes the 1 day
        req1 = create_leave_request("E001", "comp_off", "2026-11-23", "2026-11-23",
                                    "Comp off day", "2026-11-05", db)
        assert req1 > 0

        # Second request attempts to use comp-off again while req1 is pending -> MUST BE REJECTED
        with pytest.raises(LeaveError, match="Insufficient unreserved comp-off"):
            create_leave_request("E001", "comp_off", "2026-11-24", "2026-11-24",
                                 "Duplicate comp off attempt", "2026-11-05", db)

    def test_flag_expired_records_via_refresh(self, db: Path) -> None:
        """Item 7: refresh_comp_off_status flags available records past expiry as expired."""
        with connection(db) as conn:
            conn.execute(
                """INSERT INTO comp_off_records(employee_id, earned_on, expires_on, days, status)
                   VALUES ('E001', '2026-01-01', '2026-02-01', 1.0, 'available')"""
            )
        # As of 2026-03-01, this record is past expiry
        updated = refresh_comp_off_status(as_of="2026-03-01", db_path=db)
        assert updated >= 1
        with connection(db) as conn:
            row = conn.execute(
                "SELECT status FROM comp_off_records WHERE employee_id='E001' AND expires_on='2026-02-01'"
            ).fetchone()
            assert row["status"] == "expired"

    def test_display_calendar_breakdown_of_holidays_and_working_days(self, db: Path) -> None:
        """Item 8: get_calendar_breakdown lists working days, weekends, public and optional holidays."""
        # 2026-11-19 (Thu) to 2026-11-23 (Mon)
        # Seeded: 2026-11-20 is an optional holiday. Nov 21 (Sat), Nov 22 (Sun).
        breakdown = get_calendar_breakdown("2026-11-19", "2026-11-23", db_path=db)
        assert len(breakdown) == 5

        by_date = {d["date"]: d for d in breakdown}
        assert by_date["2026-11-19"]["is_working_day"] is True
        assert by_date["2026-11-20"]["is_optional_holiday"] is True
        assert by_date["2026-11-21"]["is_weekend"] is True
        assert by_date["2026-11-22"]["is_weekend"] is True
        assert by_date["2026-11-23"]["is_working_day"] is True

        # When optional holiday is claimed/excluded:
        breakdown_claimed = get_calendar_breakdown("2026-11-19", "2026-11-23", db_path=db, exclude_optional_holidays=True)
        by_date_claimed = {d["date"]: d for d in breakdown_claimed}
        assert by_date_claimed["2026-11-20"]["is_working_day"] is False
        assert "Claimed" in by_date_claimed["2026-11-20"]["status_label"]

    def test_explain_leave_interaction_annual_and_comp_off(self, db: Path) -> None:
        """Item 9: explain_leave_interaction details holiday exclusions, FIFO comp-off consumption, and balances."""
        # 1. Annual leave spanning weekend and public holiday (2026-12-21 Mon to 2026-12-25 Fri with winter holiday on Fri)
        exp_annual = explain_leave_interaction("annual", "2026-12-21", "2026-12-25",
                                               employee_id="E001", db_path=db)
        assert exp_annual["total_calendar_days"] == 5
        assert exp_annual["chargeable_working_days"] == 4
        assert len(exp_annual["public_holidays"]) == 1
        assert "not charged" in exp_annual["explanation_summary"].lower() or "excluded" in exp_annual["explanation_summary"].lower()

        # 2. Comp-off leave explanation
        exp_compoff = explain_leave_interaction("comp_off", "2026-12-07", "2026-12-08",
                                                employee_id="E001", db_path=db)
        assert "comp_off_info" in exp_compoff
        assert exp_compoff["comp_off_info"] is not None
        assert "records_to_consume" in exp_compoff["comp_off_info"]


# ==============================================================================
# SECTION C: WORKFORCE PLANNING & TIMELINES (Items 10 - 15)
# ==============================================================================

class TestWorkforceAndTimelines:
    """Items 10, 11, 12, 13, 14, 15: Leave timelines, return-to-work, notice/approval due dates, alerts, overlap query."""

    def test_calculate_return_to_work_date(self, db: Path) -> None:
        """Item 10: Expected return date is the first working day after leave ends, skipping weekends/holidays."""
        # Leave ends on Friday 2026-11-13 -> Return date is Monday 2026-11-16
        ret = calculate_return_to_work_date("2026-11-13", db_path=db)
        assert ret.isoformat() == "2026-11-16"

        # Leave ends on Thursday 2026-12-24. 2026-12-25 (Fri) is seeded public holiday.
        # Sat 26, Sun 27 -> Return date is Monday 2026-12-28!
        ret_holiday = calculate_return_to_work_date("2026-12-24", db_path=db)
        assert ret_holiday.isoformat() == "2026-12-28"

    def test_automatic_generation_of_approval_and_return_to_work_timeline_events(self, db: Path) -> None:
        """Item 10 & 11: Leave request submission generates approval_deadline; approval generates return_to_work."""
        mgr = UserContext("E005", "Kiran Rao", "manager", "T01")
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")

        # 1. Submit leave request -> approval deadline timeline item automatically generated
        req_id = create_leave_request("E001", "annual", "2026-12-07", "2026-12-09",
                                      "Vacation trip", "2026-11-01", db)
        tl_items = list_timeline(mgr, "2026-11-01", "2026-12-31", db_path=db)
        app_item = next((t for t in tl_items if t["item_type"] == "approval_deadline" and f"#{req_id}" in t["title"]), None)
        assert app_item is not None
        assert app_item["status"] == "active"
        assert app_item["due_on"] == "2026-11-04"  # 3 days after Nov 1 submission

        # 2. Manager approves leave -> approval item completed, return_to_work item generated
        decide_leave_request(mgr, req_id, "approved", "Approved by manager", "2026-11-02", db)

        tl_items_after = list_timeline(mgr, "2026-11-01", "2026-12-31", db_path=db)
        # Approval deadline item is completed
        app_item_after = next(t for t in tl_items_after if t["item_id"] == app_item["item_id"])
        assert app_item_after["status"] == "completed"

        # Return to work item created
        rtw_item = next((t for t in tl_items_after if t["item_type"] == "return_to_work" and "E001" in t["title"]), None)
        assert rtw_item is not None
        assert rtw_item["due_on"] == "2026-12-10"  # Next day after Wednesday Dec 9 is Thursday Dec 10

    def test_alerts_show_overdue_approval_and_comp_off_expiry(self, db: Path) -> None:
        """Item 12 & 13: System displays upcoming events and overdue alerts for approvals and expiring comp-off."""
        mgr = UserContext("E005", "Kiran Rao", "manager", "T01")

        # Create leave request with approval due on 2026-11-04
        req_id = create_leave_request("E001", "annual", "2026-12-14", "2026-12-18",
                                      "Long break", "2026-11-01", db)

        # Grant comp-off expiring on 2026-11-15
        record_comp_off(mgr, "E001", "2026-11-01", "2026-11-15", 1.0, db, "Overtime")

        # As of Nov 10 (after approval due date Nov 4):
        alerts = get_alerts(mgr, as_of="2026-11-10", horizon_days=30, db_path=db)

        # Must have an approval_overdue alert
        overdue_alert = next((a for a in alerts if a["type"] == "approval_overdue" and f"#{req_id}" in a["message"]), None)
        assert overdue_alert is not None
        assert overdue_alert["severity"] == "high"

        # Must have comp-off expiring soon alert
        compoff_alert = next((a for a in alerts if a["type"] == "comp_off_expiry" and "E001" in a["message"]), None)
        assert compoff_alert is not None

    def test_detect_low_coverage_and_missing_backup_assignments(self, db: Path) -> None:
        """Item 14: System detects critical project deadlines without backup and triggers alerts."""
        mgr = UserContext("E005", "Kiran Rao", "manager", "T01")

        with connection(db) as conn:
            # Insert critical deadline with NO backup assignment
            conn.execute(
                """INSERT INTO project_deadlines(title, due_on, team_id, critical, owner_id)
                   VALUES ('Production Kernel Upgrade', '2026-11-18', 'T01', 1, 'E001')"""
            )

        alerts = get_alerts(mgr, as_of="2026-11-10", horizon_days=20, db_path=db)
        missing_bk = next((a for a in alerts if a["type"] == "missing_backup" and "Production Kernel Upgrade" in a["message"]), None)
        assert missing_bk is not None
        assert missing_bk["severity"] == "high"

    def test_query_timeline_overlap_inquiry(self, db: Path) -> None:
        """Item 15: Allow timeline questions such as deadlines overlapping a proposed leave period."""
        emp = UserContext("E001", "Rahul Sharma", "employee", "T01")

        with connection(db) as conn:
            # Deadline 1: Critical, owned by E001, NO backup
            conn.execute(
                """INSERT INTO project_deadlines(title, due_on, team_id, critical, owner_id)
                   VALUES ('Quarterly ML Audit', '2026-12-08', 'T01', 1, 'E001')"""
            )
            # Deadline 2: Critical, owned by E002, WITH backup
            conn.execute(
                """INSERT INTO project_deadlines(title, due_on, team_id, critical, owner_id)
                   VALUES ('Data Pipeline Sync', '2026-12-09', 'T01', 1, 'E002')"""
            )
            dl2_id = conn.execute("SELECT deadline_id FROM project_deadlines WHERE title='Data Pipeline Sync'").fetchone()[0]
            conn.execute(
                "INSERT INTO backup_assignments(deadline_id, backup_employee_id, assigned_on) VALUES (?, ?, '2026-11-01')",
                (dl2_id, "E001")
            )

        # E001 proposes leave from Dec 07 to Dec 10
        overlap = query_timeline_overlap(emp, "T01", "2026-12-07", "2026-12-10", employee_id="E001", db_path=db)

        assert overlap["deadlines_count"] >= 2
        assert len(overlap["critical_owned_deadlines"]) >= 1
        assert len(overlap["critical_deadlines_missing_backup"]) >= 1
        assert overlap["has_operational_risk"] is True
        assert "HIGH OPERATIONAL RISK" in overlap["explanation"]
        assert "Quarterly ML Audit" in [d["title"] for d in overlap["deadlines"]]
