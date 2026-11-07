"""Phase 3 deterministic leave workflow tests."""
from datetime import date
import pytest

from database.db import initialize, connection
from database.seed import seed
from leave_management.service import (
    LeaveError, add_holiday, create_leave_request, decide_leave_request,
    get_balance, list_holidays, refresh_comp_off_status, working_days,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "phase3.db"
    initialize(path)
    # Seed uses the configured default DB, so populate this isolated DB explicitly
    with connection(path) as conn:
        conn.executemany("INSERT INTO teams(team_id,name,min_coverage_percent) VALUES (?,?,?)",
                         [("T1","Team One",60)])
        conn.executemany("""INSERT INTO employees
            (employee_id,name,email,role,team_id,manager_id,joined_on)
            VALUES (?,?,?,?,?,?,?)""", [
            ("M1","Manager","m1@test.invalid","manager","T1",None,"2025-01-01"),
            ("H1","HR","h1@test.invalid","hr","T1",None,"2025-01-01"),
            ("E1","Employee","e1@test.invalid","employee","T1","M1","2025-01-01"),
        ])
        conn.executemany("""INSERT INTO leave_balances
            (employee_id,leave_type,year,entitled_days,used_days) VALUES (?,?,?,?,?)""", [
            ("E1","annual",2026,18,2),("E1","sick",2026,10,1)])
        conn.executemany("INSERT INTO holidays(date,name,holiday_type) VALUES (?,?,?)", [
            ("2026-11-11","Public day","public"),
            ("2026-11-12","Optional day","optional")])
        conn.execute("""INSERT INTO comp_off_records
            (employee_id,earned_on,expires_on,days,status)
            VALUES ('E1','2026-10-01','2026-12-30',1,'available')""")
    return path


def test_working_days_excludes_weekends_and_public_not_optional(db):
    # Mon 9, Tue 10, Wed 11 (public), Thu 12 (optional), Fri 13 Nov 2026
    assert working_days("2026-11-09", "2026-11-13", db) == 4


def test_balance_remaining(db):
    assert get_balance("E1","annual",2026,db)["remaining_days"] == 16.0


def test_create_annual_request_calculates_days(db):
    request_id = create_leave_request(
        "E1","annual","2026-11-09","2026-11-13",
        submitted_on="2026-11-01",db_path=db)
    with connection(db) as conn:
        row = conn.execute("SELECT requested_days,status FROM leave_requests WHERE request_id=?",
                           (request_id,)).fetchone()
    assert row["requested_days"] == 4
    assert row["status"] == "pending"


def test_annual_notice_rule(db):
    with pytest.raises(LeaveError, match="5 calendar days"):
        create_leave_request("E1","annual","2026-11-05","2026-11-05",
                             submitted_on="2026-11-01",db_path=db)


def test_overlap_is_rejected(db):
    create_leave_request("E1","sick","2026-11-16","2026-11-16",
                         submitted_on="2026-11-01",db_path=db)
    with pytest.raises(LeaveError, match="overlap"):
        create_leave_request("E1","sick","2026-11-16","2026-11-17",
                             submitted_on="2026-11-01",db_path=db)


def test_approval_deducts_balance_and_updates_attendance(db):
    rid = create_leave_request("E1","annual","2026-11-16","2026-11-17",
                               submitted_on="2026-11-01",db_path=db)
    decide_leave_request(rid,"approved","M1",decided_on="2026-11-02",db_path=db)
    assert get_balance("E1","annual",2026,db)["used_days"] == 4.0
    with connection(db) as conn:
        status = conn.execute("SELECT status FROM leave_requests WHERE request_id=?",(rid,)).fetchone()[0]
        attendance = conn.execute("SELECT COUNT(*) FROM attendance WHERE employee_id='E1' AND date BETWEEN '2026-11-16' AND '2026-11-17' AND status='approved_leave'").fetchone()[0]
    assert status == "approved"
    assert attendance == 2


def test_employee_cannot_approve(db):
    rid = create_leave_request("E1","sick","2026-11-16","2026-11-16",
                               submitted_on="2026-11-01",db_path=db)
    with pytest.raises(LeaveError, match="Only a manager or HR"):
        decide_leave_request(rid,"approved","E1",decided_on="2026-11-02",db_path=db)


def test_comp_off_consumed_on_approval(db):
    rid = create_leave_request("E1","comp_off","2026-11-16","2026-11-16",
                               submitted_on="2026-11-01",db_path=db)
    decide_leave_request(rid,"approved","H1",decided_on="2026-11-02",db_path=db)
    with connection(db) as conn:
        status = conn.execute("SELECT status FROM comp_off_records WHERE employee_id='E1'").fetchone()[0]
    assert status == "used"


def test_expiry_refresh(db):
    changed = refresh_comp_off_status("2026-12-31",db)
    assert changed == 1


def test_holiday_admin_and_listing(db):
    add_holiday("2026-12-25","Winter Holiday","public",db)
    assert list_holidays("2026-12-01","2026-12-31",db)[0]["name"] == "Winter Holiday"
