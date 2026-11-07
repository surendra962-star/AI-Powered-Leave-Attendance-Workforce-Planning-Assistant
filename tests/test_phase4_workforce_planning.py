"""Tests for Phase 4 workforce planning and decision support."""
import json
import pytest

from database.db import initialize, connection
from leave_management.service import LeaveError
from workforce_planning.service import (
    assign_backup, evaluate_leave_request, list_team_deadlines, team_coverage,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "phase4.db"
    initialize(path)
    with connection(path) as conn:
        conn.executemany(
            "INSERT INTO teams(team_id,name,min_coverage_percent) VALUES (?,?,?)",
            [("T1", "AI Team", 60), ("T2", "Other Team", 60)],
        )
        conn.executemany(
            """INSERT INTO employees
               (employee_id,name,email,role,team_id,manager_id,joined_on,is_active)
               VALUES (?,?,?,?,?,?,?,?)""",
            [
                ("M1", "Manager", "m1@test.invalid", "manager", "T1", None, "2025-01-01", 1),
                ("E1", "Owner", "e1@test.invalid", "employee", "T1", "M1", "2025-01-01", 1),
                ("E2", "Backup", "e2@test.invalid", "employee", "T1", "M1", "2025-01-01", 1),
                ("E3", "Colleague", "e3@test.invalid", "employee", "T1", "M1", "2025-01-01", 1),
                ("E4", "Colleague 2", "e4@test.invalid", "employee", "T1", "M1", "2025-01-01", 1),
                ("X1", "Other Team", "x1@test.invalid", "employee", "T2", None, "2025-01-01", 1),
            ],
        )
        conn.execute(
            """INSERT INTO leave_requests
               (employee_id,leave_type,start_date,end_date,requested_days,reason,status,submitted_on)
               VALUES ('E1','annual','2026-11-16','2026-11-17',2,'test','pending','2026-11-01')"""
        )
        conn.execute(
            """INSERT INTO project_deadlines(team_id,title,due_on,critical,owner_id)
               VALUES ('T1','Model delivery','2026-11-17',1,'E1')"""
        )
    return path


def test_team_coverage_counts_active_employees_and_planned_leave(db):
    with connection(db) as conn:
        conn.execute(
            """INSERT INTO leave_requests
               (employee_id,leave_type,start_date,end_date,requested_days,status,submitted_on)
               VALUES ('E3','annual','2026-11-16','2026-11-17',2,'approved','2026-11-01')"""
        )
    result = team_coverage("T1", "2026-11-16", db)
    assert result["total_active_employees"] == 5
    assert result["available_count"] == 3  # E1 pending + E3 approved are absent
    assert result["coverage_percent"] == 60.0
    assert result["meets_minimum"] is True


def test_evaluation_flags_coverage_breach_and_critical_deadline(db):
    with connection(db) as conn:
        conn.execute(
            """INSERT INTO leave_requests
               (employee_id,leave_type,start_date,end_date,requested_days,status,submitted_on)
               VALUES ('E2','annual','2026-11-16','2026-11-17',2,'approved','2026-11-01')"""
        )
        conn.execute(
            """INSERT INTO leave_requests
               (employee_id,leave_type,start_date,end_date,requested_days,status,submitted_on)
               VALUES ('E3','annual','2026-11-16','2026-11-17',2,'approved','2026-11-01')"""
        )
    result = evaluate_leave_request(1, "2026-11-02", db, persist=False)
    assert result["recommendation"] == "high_risk"
    assert result["automatic_approval"] is False
    assert result["evidence"]["coverage_breach_dates"] == ["2026-11-16", "2026-11-17"]
    assert result["evidence"]["critical_deadlines_without_available_backup"] == [1]


def test_backup_assignment_and_recommendation_history(db):
    assignment_id = assign_backup(1, "E2", "2026-11-02", db)
    assert assignment_id == 1
    result = evaluate_leave_request(1, "2026-11-02", db, persist=True)
    assert result["recommendation"] == "review_required"
    with connection(db) as conn:
        row = conn.execute(
            "SELECT recommendation,evidence_json,final_decision,decided_by,decided_on FROM decision_history WHERE request_id=1"
        ).fetchone()
    assert row["recommendation"] == "review_required"
    assert json.loads(row["evidence_json"])["project_deadlines"][0]["backup_employee_id"] == "E2"
    assert row["final_decision"] is None
    assert row["decided_by"] is None
    assert row["decided_on"] is None


def test_backup_must_belong_to_same_team(db):
    with pytest.raises(LeaveError, match="deadline.s team"):
        assign_backup(1, "X1", "2026-11-02", db)


def test_deadline_listing(db):
    rows = list_team_deadlines("T1", "2026-11-01", "2026-11-30", db)
    assert len(rows) == 1
    assert rows[0]["title"] == "Model delivery"
    assert rows[0]["backup_employee_id"] is None


def test_evaluation_rejects_already_decided_request(db):
    with connection(db) as conn:
        conn.execute("UPDATE leave_requests SET status='declined' WHERE request_id=1")
    with pytest.raises(LeaveError, match="Only pending"):
        evaluate_leave_request(1, "2026-11-02", db, persist=False)


def test_simulate_what_if_leave_feasible_and_breach(db):
    from workforce_planning.service import simulate_what_if_leave

    # Test feasible single person leave when threshold is 60% and team has 5 members (4/5 = 80%)
    res_feasible = simulate_what_if_leave(
        team_id="T1",
        candidate_employee_ids=["E2"],
        start_date="2026-11-23",  # Mon
        end_date="2026-11-24",    # Tue
        threshold_percent=60,
        db_path=db
    )
    assert res_feasible["is_feasible"] is True
    assert res_feasible["breach_days_count"] == 0
    assert res_feasible["lowest_simulated_coverage_percent"] == 80.0

    # Test breach when multiple members are absent (E2, E3, E4 -> 2/5 = 40% < 60%)
    res_breach = simulate_what_if_leave(
        team_id="T1",
        candidate_employee_ids=["E2", "E3", "E4"],
        start_date="2026-11-23",
        end_date="2026-11-24",
        threshold_percent=60,
        db_path=db
    )
    assert res_breach["is_feasible"] is False
    assert res_breach["breach_days_count"] == 2
    assert res_breach["lowest_simulated_coverage_percent"] == 40.0
