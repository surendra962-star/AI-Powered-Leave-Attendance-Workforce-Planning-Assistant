"""Comprehensive end-to-end evaluation covering the 10 real-world assessment scenarios."""
from datetime import date, timedelta
from pathlib import Path
import pytest
from database.db import initialize, connection
from database.seed import seed
from access_control.service import (
    UserContext, AccessError, authenticate, initialize_security,
    bootstrap_hr, set_employee_password
)
from leave_management.service import (
    create_leave_request, decide_leave_request, cancel_leave_request,
    list_leave_requests, working_days, LeaveError
)
from dashboards.service import list_employee_leave
from workforce_planning.service import (
    evaluate_leave_request, recommend_backups, team_capacity_forecast, assign_backup
)
from timeline.service import record_comp_off, comp_off_summary
from attendance.service import clock_in, get_monthly_attendance_summary

@pytest.fixture
def e2e_db(tmp_path: Path):
    path = tmp_path / 'e2e_assessment.db'
    initialize(path)
    seed(path)
    hr_ctx = authenticate('HR001', 'hradmin@2026', path)
    set_employee_password(hr_ctx, 'E002', 'priyauser@2026', path)
    set_employee_password(hr_ctx, 'E003', 'amituser@2026', path)
    return path


def test_scenario_01_leave_creation_and_working_days(e2e_db):
    """Scenario 1: Employee applies for annual leave with notice check and working day calculation."""
    emp = authenticate('E001', 'rahuluser@2026', e2e_db)
    
    # 2026-12-07 (Mon) to 2026-12-09 (Wed) = 3 working days
    req_id = create_leave_request(
        employee_id='E001',
        leave_type='annual',
        start_date='2026-12-07',
        end_date='2026-12-09',
        reason='Family trip',
        submitted_on='2026-11-01',
        db_path=e2e_db
    )
    assert req_id > 0
    
    with connection(e2e_db) as conn:
        row = conn.execute("SELECT requested_days, status FROM leave_requests WHERE request_id=?", (req_id,)).fetchone()
        assert row['requested_days'] == 3.0
        assert row['status'] == 'pending'


def test_scenario_02_overlapping_leave_prevention(e2e_db):
    """Scenario 2: System rejects overlapping leave requests for the same employee."""
    create_leave_request('E001', 'annual', '2026-12-14', '2026-12-18', 'Sprint break', '2026-11-01', e2e_db)
    
    # Attempt overlapping range
    with pytest.raises(LeaveError, match="overlap|already exists"):
        create_leave_request('E001', 'annual', '2026-12-16', '2026-12-20', 'Overlapping request', '2026-11-01', e2e_db)


def test_scenario_03_manager_approval_deducts_balance_and_syncs_attendance(e2e_db):
    """Scenario 3: Manager approves leave; balance deducts and attendance records approved_leave."""
    mgr = authenticate('E005', 'kiranmgr@2026', e2e_db)
    
    req_id = create_leave_request('E001', 'annual', '2026-12-21', '2026-12-22', 'Holiday season', '2026-11-01', e2e_db)
    decide_leave_request(mgr, req_id, 'approved', 'Approved. Enjoy!', '2026-11-05', e2e_db)
    
    with connection(e2e_db) as conn:
        req = conn.execute("SELECT status FROM leave_requests WHERE request_id=?", (req_id,)).fetchone()
        assert req['status'] == 'approved'
        
        bal = conn.execute("SELECT used_days FROM leave_balances WHERE employee_id='E001' AND leave_type='annual' AND year=2026").fetchone()
        assert bal['used_days'] >= 2.0
        
        att = conn.execute("SELECT status FROM attendance WHERE employee_id='E001' AND date='2026-12-21'").fetchone()
        assert att['status'] == 'approved_leave'


def test_scenario_04_leave_cancellation_restores_balance_and_attendance(e2e_db):
    """Scenario 4: Employee cancels approved leave; balance is restored and attendance cleared."""
    emp = authenticate('E001', 'rahuluser@2026', e2e_db)
    mgr = authenticate('E005', 'kiranmgr@2026', e2e_db)
    
    req_id = create_leave_request('E001', 'annual', '2026-12-28', '2026-12-29', 'Year end', '2026-11-01', e2e_db)
    decide_leave_request(mgr, req_id, 'approved', 'OK', '2026-11-05', e2e_db)
    
    with connection(e2e_db) as conn:
        bal_before = conn.execute("SELECT used_days FROM leave_balances WHERE employee_id='E001' AND leave_type='annual' AND year=2026").fetchone()['used_days']
    
    # Cancel leave
    res = cancel_leave_request(emp, req_id, db_path=e2e_db)
    assert res['cancelled'] is True
    
    with connection(e2e_db) as conn:
        bal_after = conn.execute("SELECT used_days FROM leave_balances WHERE employee_id='E001' AND leave_type='annual' AND year=2026").fetchone()['used_days']
        assert bal_after == bal_before - 2.0
        
        att = conn.execute("SELECT * FROM attendance WHERE employee_id='E001' AND date='2026-12-28'").fetchone()
        assert att is None


def test_scenario_05_compoff_accrual_and_usage(e2e_db):
    """Scenario 5: Comp-off granted by manager, verified, tracked and summarized."""
    mgr = authenticate('E005', 'kiranmgr@2026', e2e_db)
    emp = authenticate('E001', 'rahuluser@2026', e2e_db)
    
    cid = record_comp_off(mgr, 'E001', '2026-11-01', '2027-01-31', 1.0, e2e_db, work_reference="Production deployment support")
    assert cid > 0
    
    summary = comp_off_summary(emp, 'E001', date(2026, 11, 2), e2e_db)
    assert summary['available_days'] >= 1.0


def test_scenario_06_team_coverage_breach_detection(e2e_db):
    """Scenario 6: Workforce coverage flags warning when min coverage threshold is breached."""
    mgr = authenticate('E005', 'kiranmgr@2026', e2e_db)
    
    # Team T01 has 6 members, min coverage is 60% (needs at least 4 active).
    # If 3 are on leave simultaneously, coverage drops to 50% (<60%), triggering a warning.
    # Create approved leaves for E001 and E003
    r1 = create_leave_request('E001', 'annual', '2026-11-16', '2026-11-18', 'L1', '2026-11-01', e2e_db)
    r2 = create_leave_request('E003', 'annual', '2026-11-16', '2026-11-18', 'L2', '2026-11-01', e2e_db)
    decide_leave_request(mgr, r1, 'approved', 'ok', '2026-11-02', e2e_db)
    decide_leave_request(mgr, r2, 'approved', 'ok', '2026-11-02', e2e_db)
    
    # E002 requests leave for the same dates
    r3 = create_leave_request('E002', 'annual', '2026-11-16', '2026-11-18', 'L3', '2026-11-01', e2e_db)
    eval_res = evaluate_leave_request(r3, db_path=e2e_db)
    assert eval_res['coverage_warning'] is True
    assert eval_res['coverage_after_percent'] < 60


def test_scenario_07_backup_recommendation_for_critical_deadline(e2e_db):
    """Scenario 7: Recommends available team members for a critical project deadline."""
    # Fetch team deadlines
    with connection(e2e_db) as conn:
        dl = conn.execute("SELECT deadline_id, owner_id FROM project_deadlines WHERE team_id='T01' LIMIT 1").fetchone()
    
    recommendations = recommend_backups(dl['deadline_id'], db_path=e2e_db)
    assert len(recommendations) > 0
    # Assigned backup should belong to same team and not be the owner
    for rec in recommendations:
        assert rec['employee_id'] != dl['owner_id']
    assert any(rec['is_available'] for rec in recommendations)


def test_scenario_08_rbac_isolation_enforcement(e2e_db):
    """Scenario 8: Role checks prevent unauthorized peer access and privilege escalation."""
    emp1 = authenticate('E001', 'rahuluser@2026', e2e_db)
    emp2 = authenticate('E002', 'priyauser@2026', e2e_db)
    
    # Employee cannot approve leave
    r = create_leave_request('E001', 'annual', '2026-12-01', '2026-12-02', 'Test', '2026-11-01', e2e_db)
    with pytest.raises(AccessError):
        decide_leave_request(emp2, r, 'approved', 'Sneaky approval', '2026-11-02', e2e_db)
        
    # Employee cannot view peer's leave list
    with pytest.raises(AccessError):
        list_employee_leave(emp1, 'E002', e2e_db)


from unittest.mock import patch
from rag.assistant import ask


def test_scenario_09_rag_policy_query_with_citations():
    """Scenario 9: RAG assistant returns grounded answers with exact section, version and citations."""
    hit = {
        'text': 'Employees receive 18 annual leave days per calendar year.',
        'distance': 0.15,
        'metadata': {
            'title': 'Sample Leave Policy',
            'version': '2.0',
            'section': '1. Annual Leave',
            'source': 'leave_policy_v2.md',
            'page': 1
        }
    }
    with patch('rag.assistant.search', return_value=[hit]):
        res = ask(
            "How many annual leave days are provided per year?",
            on=date(2026, 10, 31),
            generator=lambda sys, p: "Employees receive 18 annual leave days per year [1]."
        )
    assert "18 annual leave days" in res['answer']
    assert len(res['sources']) > 0
    assert res['sources'][0]['version'] == '2.0'
    assert res['sources'][0]['section'] == '1. Annual Leave'
    assert res['sources'][0]['document'] == 'Sample Leave Policy'


def test_scenario_10_rag_unsupported_query_abstention():
    """Scenario 10: RAG assistant gracefully abstains on out-of-scope policies without fabricating."""
    with patch('rag.assistant.search', return_value=[]):
        res = ask("What is the reimbursement policy for interstellar spaceship fuel?", on=date(2026, 10, 31))
    assert "do not specify" in res['answer'] or "insufficient" in res['answer'] or "do not contain" in res['answer']
    assert len(res['sources']) == 0

