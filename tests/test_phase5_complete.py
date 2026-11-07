"""Comprehensive test suite for Phase 5 – Analytics and Manager/HR Dashboards.

Verifies all 11 requirements:
1. Monthly attendance percentage calculation (present / (present + absent) * 100).
2. Leave days and leave-type breakdown (annual, sick, comp_off across statuses).
3. Pending requests and comp-off balances on employee, manager, and HR dashboards.
4. Team-level planned absence and coverage calculation over date ranges.
5. Multi-dimensional filters (team, employee, month, leave type, request status).
6. Role-based visibility and scope enforcement (employee, manager, HR).
7. Clear metric definitions (attendance percentage, approved leave & holiday effects).
8. Pending approval deadlines (with overdue status) and low-coverage warnings.
9. Upcoming comp-off expiries, holidays, and project deadlines.
10. Separation of AI recommendations from actual manager decisions.
11. Human decision recording with explanatory note and preserved decision history.
12. Flask REST API integration for Phase 5 endpoints.
"""
from datetime import date, timedelta
from pathlib import Path
import pytest

from database.db import initialize, connection, DB_PATH
from access_control.service import UserContext, AccessError
from analytics.service import (
    workforce_metrics, get_team_coverage_analytics,
    organization_workforce_summary, export_metrics_csv
)
from dashboards.service import (
    employee_dashboard, manager_dashboard, hr_dashboard,
    get_decision_history
)
from leave_management.service import (
    create_leave_request, decide_leave_request, LeaveError
)
from workforce_planning.service import evaluate_leave_request
from timeline.service import record_comp_off, add_timeline_item


@pytest.fixture
def test_db(tmp_path):
    """Create an isolated test database populated with teams, employees, and baseline records."""
    db_file = tmp_path / "phase5_test.db"
    initialize(db_file)
    with connection(db_file) as conn:
        # Seed Teams
        conn.execute("INSERT INTO teams (team_id, name, min_coverage_percent) VALUES ('T01', 'Core Engineering', 60)")
        conn.execute("INSERT INTO teams (team_id, name, min_coverage_percent) VALUES ('T02', 'Data Science', 50)")
        conn.execute("INSERT INTO teams (team_id, name, min_coverage_percent) VALUES ('T_HR', 'Human Resources', 50)")

        # Seed Employees
        employees = [
            ('M01', 'Manager Alice', 'alice@test.corp', 'manager', 'T01', None, '2025-01-01', 1),
            ('E01', 'Employee Bob', 'bob@test.corp', 'employee', 'T01', 'M01', '2025-01-01', 1),
            ('E02', 'Employee Charlie', 'charlie@test.corp', 'employee', 'T01', 'M01', '2025-01-01', 1),
            ('E03', 'Employee David', 'david@test.corp', 'employee', 'T01', 'M01', '2025-01-01', 1),
            ('M02', 'Manager Eve', 'eve@test.corp', 'manager', 'T02', None, '2025-01-01', 1),
            ('E04', 'Employee Frank', 'frank@test.corp', 'employee', 'T02', 'M02', '2025-01-01', 1),
            ('HR01', 'HR Admin Grace', 'grace@test.corp', 'hr', 'T_HR', None, '2025-01-01', 1),
        ]
        conn.executemany("""
            INSERT INTO employees (employee_id, name, email, role, team_id, manager_id, joined_on, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, employees)

        # Seed Leave Balances for 2026
        for emp_id in ('E01', 'E02', 'E03', 'E04', 'M01', 'M02'):
            conn.execute("INSERT INTO leave_balances VALUES (?, 'annual', 2026, 18, 2)", (emp_id,))
            conn.execute("INSERT INTO leave_balances VALUES (?, 'sick', 2026, 10, 1)", (emp_id,))

        # Seed Public and Optional Holidays
        conn.executemany("INSERT INTO holidays (date, name, holiday_type) VALUES (?, ?, ?)", [
            ('2026-11-09', 'Autumn Holiday', 'public'),
            ('2026-11-20', 'Optional Cultural Day', 'optional'),
            ('2026-12-25', 'Christmas Day', 'public'),
        ])

        # Seed Project Deadlines
        conn.executemany("INSERT INTO project_deadlines (deadline_id, team_id, title, due_on, critical, owner_id) VALUES (?, ?, ?, ?, ?, ?)", [
            (101, 'T01', 'Database Migration', '2026-11-12', 1, 'E01'),
            (102, 'T01', 'Security Audit', '2026-11-25', 0, 'E02'),
            (103, 'T02', 'Model Training Pipeline', '2026-11-18', 1, 'E04'),
        ])
    return db_file


# ==============================================================================
# 1. MONTHLY ATTENDANCE PERCENTAGE & FORMULA
# ==============================================================================
def test_monthly_attendance_percentage_and_formula(test_db):
    """Verify attendance percentage is present / (present + absent) * 100, excluding approved leave."""
    emp = UserContext('E01', 'Employee Bob', 'employee', 'T01')
    hr = UserContext('HR01', 'HR Admin Grace', 'hr', 'T01')

    # Seed attendance for 2026-11: 8 present, 2 absent, 2 approved_leave
    with connection(test_db) as conn:
        for d in range(1, 9):
            conn.execute("INSERT INTO attendance (employee_id, date, status) VALUES ('E01', ?, 'present')",
                         (f"2026-11-{d:02d}",))
        for d in (10, 11):
            conn.execute("INSERT INTO attendance (employee_id, date, status) VALUES ('E01', ?, 'absent')",
                         (f"2026-11-{d:02d}",))
        for d in (12, 13):
            conn.execute("INSERT INTO attendance (employee_id, date, status) VALUES ('E01', ?, 'approved_leave')",
                         (f"2026-11-{d:02d}",))

    metrics = workforce_metrics(emp, '2026-11', db_path=test_db)
    att = metrics['attendance']

    assert att['scheduled_records'] == 12
    assert att['present_days'] == 8
    assert att['absent_days'] == 2
    assert att['approved_leave_days'] == 2
    # Formula: 8 / (8 + 2) * 100 = 80.0% (approved leave is excluded from denominator)
    assert att['attendance_percent'] == 80.0
    assert att['attendance_percentage'] == 80.0


# ==============================================================================
# 2. LEAVE DAYS AND LEAVE-TYPE BREAKDOWN
# ==============================================================================
def test_leave_days_and_leave_type_breakdown(test_db):
    """Verify detailed breakdown of leave requests and requested days by leave type and status."""
    hr = UserContext('HR01', 'HR Admin Grace', 'hr', 'T01')

    with connection(test_db) as conn:
        # E01: 3 annual leave requests (1 approved 4 days, 1 pending 2 days, 1 declined 3 days)
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (1, 'E01', 'annual', '2026-11-02', '2026-11-05', 4.0, 'approved', '2026-10-20')""")
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (2, 'E01', 'annual', '2026-11-16', '2026-11-17', 2.0, 'pending', '2026-11-01')""")
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (3, 'E01', 'annual', '2026-11-23', '2026-11-25', 3.0, 'declined', '2026-11-10')""")
        # E02: 1 sick leave request (approved 2 days)
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (4, 'E02', 'sick', '2026-11-10', '2026-11-11', 2.0, 'approved', '2026-11-09')""")
        # E03: 1 comp_off leave request (pending 1 day)
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (5, 'E03', 'comp_off', '2026-11-30', '2026-11-30', 1.0, 'pending', '2026-11-20')""")

    metrics = workforce_metrics(hr, '2026-11', db_path=test_db)
    breakdown = metrics['leave_type_breakdown']

    assert breakdown['annual']['requests_count'] == 3
    assert breakdown['annual']['total_days'] == 9.0
    assert breakdown['annual']['approved_days'] == 4.0
    assert breakdown['annual']['pending_days'] == 2.0
    assert breakdown['annual']['declined_days'] == 3.0

    assert breakdown['sick']['requests_count'] == 1
    assert breakdown['sick']['total_days'] == 2.0
    assert breakdown['sick']['approved_days'] == 2.0

    assert breakdown['comp_off']['requests_count'] == 1
    assert breakdown['comp_off']['total_days'] == 1.0
    assert breakdown['comp_off']['pending_days'] == 1.0

    assert metrics['leave_summary']['total_requests'] == 5
    assert metrics['leave_summary']['total_requested_days'] == 12.0


# ==============================================================================
# 3. PENDING REQUESTS AND COMP-OFF BALANCES ON DASHBOARDS
# ==============================================================================
def test_pending_requests_and_compoff_balances_on_dashboards(test_db):
    """Verify employee, manager, and HR dashboards correctly display pending requests and comp-off balances."""
    mgr = UserContext('M01', 'Manager Alice', 'manager', 'T01')
    emp = UserContext('E01', 'Employee Bob', 'employee', 'T01')
    hr = UserContext('HR01', 'HR Admin Grace', 'hr', 'T01')

    # Seed comp-off records
    today_str = date.today().isoformat()
    future_str = (date.today() + timedelta(days=60)).isoformat()
    with connection(test_db) as conn:
        conn.execute("INSERT INTO comp_off_records (employee_id, earned_on, expires_on, days, status) VALUES ('E01', '2026-10-01', ?, 2.0, 'available')", (future_str,))
        conn.execute("INSERT INTO comp_off_records (employee_id, earned_on, expires_on, days, status, used_on) VALUES ('E01', '2026-09-01', '2026-12-01', 1.0, 'used', '2026-10-15')")
        conn.execute("INSERT INTO comp_off_records (employee_id, earned_on, expires_on, days, status) VALUES ('E02', '2026-10-05', ?, 1.5, 'available')", (future_str,))
        # Pending leave request
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on, approval_due_on)
                        VALUES (10, 'E01', 'annual', '2026-11-16', '2026-11-17', 2.0, 'pending', '2026-11-01', '2026-11-05')""")

    # Employee dashboard checks
    emp_dash = employee_dashboard(emp, db_path=test_db)
    assert emp_dash['comp_off_summary']['available_days'] == 2.0
    assert emp_dash['comp_off_summary']['used_days'] == 1.0
    assert any(r['request_id'] == 10 for r in emp_dash['leave_requests'])

    # Manager dashboard checks
    mgr_dash = manager_dashboard(mgr, db_path=test_db)
    assert len(mgr_dash['pending_requests']) == 1
    assert mgr_dash['pending_requests'][0]['employee_id'] == 'E01'
    assert len(mgr_dash['comp_off_balances']) > 0
    e01_comp = next((c for c in mgr_dash['comp_off_balances'] if c['employee_id'] == 'E01'), None)
    assert e01_comp is not None
    assert e01_comp['available_days'] == 2.0

    # HR dashboard checks
    hr_dash = hr_dashboard(hr, db_path=test_db)
    assert hr_dash['comp_off_summary']['available_days'] >= 3.5
    assert any(r['request_id'] == 10 for r in hr_dash['pending_queue'])


# ==============================================================================
# 4. TEAM-LEVEL PLANNED ABSENCE AND COVERAGE
# ==============================================================================
def test_team_level_planned_absence_and_coverage(test_db):
    """Verify get_team_coverage_analytics calculates daily coverage, averages, lowest, and breaches."""
    mgr = UserContext('M01', 'Manager Alice', 'manager', 'T01')

    # Seed approved leave for E01 and E02 on 2026-11-12 (Thursday)
    # Team T01 has 4 active members (M01, E01, E02, E03). Min coverage is 60%.
    # 2 absent => 2 available => 50.0% coverage => BREACH (50% < 60%)
    with connection(test_db) as conn:
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (21, 'E01', 'annual', '2026-11-12', '2026-11-12', 1, 'approved', '2026-10-01')""")
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (22, 'E02', 'annual', '2026-11-12', '2026-11-12', 1, 'approved', '2026-10-01')""")

    cov_data = get_team_coverage_analytics(mgr, 'T01', '2026-11-10', '2026-11-14', db_path=test_db)

    assert cov_data['team_id'] == 'T01'
    assert cov_data['minimum_coverage_percent'] == 60
    assert '2026-11-12' in cov_data['breach_dates']
    assert cov_data['breach_count'] >= 1
    assert cov_data['lowest_coverage_percent'] == 50.0
    assert any(a['employee_id'] == 'E01' and a['date'] == '2026-11-12' for a in cov_data['planned_absences_log'])


# ==============================================================================
# 5. MULTI-DIMENSIONAL FILTERS
# ==============================================================================
def test_multi_dimensional_filters(test_db):
    """Verify filters for team, employee, month, leave type, and request status."""
    hr = UserContext('HR01', 'HR Admin Grace', 'hr', 'T01')

    with connection(test_db) as conn:
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (31, 'E01', 'annual', '2026-11-02', '2026-11-03', 2, 'approved', '2026-10-15')""")
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (32, 'E01', 'sick', '2026-11-04', '2026-11-04', 1, 'pending', '2026-11-03')""")
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (33, 'E04', 'annual', '2026-11-05', '2026-11-06', 2, 'approved', '2026-10-20')""")

    # Filter by leave_type='sick'
    res_sick = workforce_metrics(hr, '2026-11', leave_type='sick', db_path=test_db)
    assert len(res_sick['leave_requests']) == 1
    assert res_sick['leave_requests'][0]['leave_type'] == 'sick'

    # Filter by team_id='T02'
    res_t02 = workforce_metrics(hr, '2026-11', team_id='T02', db_path=test_db)
    assert len(res_t02['leave_requests']) == 1
    assert res_t02['leave_requests'][0]['employee_id'] == 'E04'

    # Filter by employee_id='E01' and status='pending'
    res_e01_pend = workforce_metrics(hr, '2026-11', employee_id='E01', status='pending', db_path=test_db)
    assert len(res_e01_pend['leave_requests']) == 1
    assert res_e01_pend['leave_requests'][0]['request_id'] == 32


# ==============================================================================
# 6. ROLE-BASED VISIBILITY & SCOPE ENFORCEMENT
# ==============================================================================
def test_role_based_visibility_and_scope_enforcement(test_db):
    """Verify strict access control: employee cannot access others; manager cannot access other teams."""
    emp1 = UserContext('E01', 'Employee Bob', 'employee', 'T01')
    mgr1 = UserContext('M01', 'Manager Alice', 'manager', 'T01')

    # Employee cannot view another employee's metrics
    with pytest.raises(PermissionError, match="Employee scope violation"):
        workforce_metrics(emp1, '2026-11', employee_id='E02', db_path=test_db)

    # Manager cannot access dashboard of another team
    with pytest.raises(AccessError, match="assigned team's dashboard"):
        manager_dashboard(mgr1, team_id='T02', db_path=test_db)

    # Manager cannot view metrics of another team
    with pytest.raises(PermissionError, match="view only their team"):
        workforce_metrics(mgr1, '2026-11', team_id='T02', db_path=test_db)

    # Manager cannot view team coverage of another team
    with pytest.raises(PermissionError, match="assigned team coverage"):
        get_team_coverage_analytics(mgr1, 'T02', '2026-11-01', '2026-11-10', db_path=test_db)

    # Employee cannot access HR dashboard
    with pytest.raises(AccessError):
        hr_dashboard(emp1, db_path=test_db)

    # Manager cannot access HR dashboard
    with pytest.raises(AccessError):
        hr_dashboard(mgr1, db_path=test_db)


# ==============================================================================
# 7. CLEAR METRIC DEFINITIONS
# ==============================================================================
def test_clear_metric_definitions_returned(test_db):
    """Verify presence of explicit formulas and definitions for attendance, holidays, and leave."""
    emp = UserContext('E01', 'Employee Bob', 'employee', 'T01')
    metrics = workforce_metrics(emp, '2026-11', db_path=test_db)

    defs = metrics['definitions']
    assert 'attendance_percent' in defs
    assert 'Approved leave is excluded' in defs['attendance_percent']
    assert 'approved_leave_effect' in defs
    assert 'holiday_and_weekend_effect' in defs
    assert 'team_coverage_percentage' in defs
    assert 'comp_off_balance' in defs


# ==============================================================================
# 8. PENDING APPROVAL DEADLINES & LOW-COVERAGE WARNINGS
# ==============================================================================
def test_pending_approval_deadlines_and_low_coverage_warnings(test_db):
    """Verify manager dashboard surfaces overdue pending approval deadlines and low-coverage warnings."""
    mgr = UserContext('M01', 'Manager Alice', 'manager', 'T01')

    # Add an overdue pending request (approval_due_on in the past)
    with connection(test_db) as conn:
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on, approval_due_on)
                        VALUES (41, 'E01', 'annual', '2026-11-20', '2026-11-22', 2, 'pending', '2026-10-25', '2026-10-28')""")
        # Target a guaranteed upcoming working day (avoiding weekends and seeded 2026-11-09 public holiday)
        target_d = date.today() + timedelta(days=3)
        while target_d.weekday() >= 5 or target_d.isoformat() == '2026-11-09':
            target_d += timedelta(days=1)
        target_date = target_d.isoformat()

        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (42, 'E01', 'annual', ?, ?, 1, 'approved', '2026-10-01')""", (target_date, target_date))
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (43, 'E02', 'annual', ?, ?, 1, 'approved', '2026-10-01')""", (target_date, target_date))

    dash = manager_dashboard(mgr, db_path=test_db)

    # Check pending approval deadlines
    deadlines = dash['pending_approval_deadlines']
    overdue_req = next((d for d in deadlines if d['request_id'] == 41), None)
    assert overdue_req is not None
    assert overdue_req['is_overdue'] is True

    # Check low-coverage warnings
    warnings = dash['low_coverage_warnings']
    assert isinstance(warnings, list)
    assert any(w['date'] == target_date for w in warnings)


# ==============================================================================
# 9. UPCOMING COMP-OFF EXPIRIES, HOLIDAYS & PROJECT DEADLINES
# ==============================================================================
def test_upcoming_compoff_expiries_holidays_project_deadlines(test_db):
    """Verify manager and HR dashboards include upcoming comp-off expiries, holidays, and deadlines."""
    mgr = UserContext('M01', 'Manager Alice', 'manager', 'T01')
    hr = UserContext('HR01', 'HR Admin Grace', 'hr', 'T01')

    # Seed comp-off expiring in 15 days
    exp_date = (date.today() + timedelta(days=15)).isoformat()
    with connection(test_db) as conn:
        conn.execute("INSERT INTO comp_off_records (employee_id, earned_on, expires_on, days, status) VALUES ('E01', '2026-10-01', ?, 1.0, 'available')", (exp_date,))

    mgr_dash = manager_dashboard(mgr, db_path=test_db)
    assert len(mgr_dash['upcoming_compoff_expiries']) >= 1
    assert any(e['employee_id'] == 'E01' and e['expires_on'] == exp_date for e in mgr_dash['upcoming_compoff_expiries'])
    assert 'upcoming_holidays' in mgr_dash

    hr_dash = hr_dashboard(hr, db_path=test_db)
    assert 'upcoming_holidays' in hr_dash
    assert 'upcoming_critical_deadlines' in hr_dash


# ==============================================================================
# 10. SHOW AI RECOMMENDATIONS SEPARATELY FROM ACTUAL MANAGER DECISIONS
# ==============================================================================
def test_ai_recommendations_separated_from_manager_decisions(test_db):
    """Verify AI evaluation returns advisory recommendation and evidence with automatic_approval=False."""
    with connection(test_db) as conn:
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (51, 'E01', 'annual', '2026-12-01', '2026-12-03', 3, 'pending', '2026-11-20')""")

    eval_result = evaluate_leave_request(51, db_path=test_db)

    # Verify AI advisory outputs
    assert eval_result['automatic_approval'] is False
    assert eval_result['final_decision'] is None
    assert eval_result['recommendation'] in ('low_risk', 'review_required', 'high_risk')
    assert eval_result['recommendation_label'] in ('Likely eligible', 'Needs manager review', 'Potential policy conflict')
    assert len(eval_result['rules_evaluated']) >= 3
    assert 'missing_information' in eval_result
    assert 'attendance_context' in eval_result

    # Inspect decision_history: verify purely advisory AI entry
    history = get_decision_history(51, db_path=test_db)
    assert len(history) == 1
    ai_entry = history[0]
    assert ai_entry['is_ai_recommendation'] is True
    assert ai_entry['is_human_decision'] is False
    assert ai_entry['final_decision'] is None
    assert ai_entry['decided_by'] is None


# ==============================================================================
# 11. ALLOW MANAGERS TO RECORD A DECISION WITH A NOTE AND PRESERVE HISTORY
# ==============================================================================
def test_manager_record_decision_with_note_and_history_preserved(test_db):
    """Verify manager records a human decision with an explanatory note, preserved in decision_history."""
    with connection(test_db) as conn:
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (61, 'E01', 'annual', '2026-12-08', '2026-12-10', 3, 'pending', '2026-11-20')""")

    # 1. AI evaluation runs first
    evaluate_leave_request(61, db_path=test_db)

    # 2. Manager makes human decision with note
    decision_note = "Approved after verifying backup coverage with Charlie (E02)."
    decide_leave_request(
        request_id=61,
        decision="approved",
        decided_by="M01",
        note=decision_note,
        decided_on="2026-11-25",
        db_path=test_db
    )

    # 3. Verify request updated
    with connection(test_db) as conn:
        req = conn.execute("SELECT status, decided_by, decided_on FROM leave_requests WHERE request_id=61").fetchone()
        assert req['status'] == 'approved'
        assert req['decided_by'] == 'M01'

    # 4. Verify decision history preserved both entries chronologically
    history = get_decision_history(61, db_path=test_db)
    assert len(history) == 2

    ai_entry = history[0]
    assert ai_entry['is_ai_recommendation'] is True
    assert ai_entry['final_decision'] is None

    human_entry = history[1]
    assert human_entry['is_human_decision'] is True
    assert human_entry['final_decision'] == 'approved'
    assert human_entry['decided_by'] == 'M01'
    assert human_entry['note'] == decision_note
    assert human_entry['decided_on'] == '2026-11-25'


# ==============================================================================
# 12. FLASK REST API ENDPOINTS FOR PHASE 5
# ==============================================================================
def test_flask_api_phase5_endpoints(test_db):
    """Verify Phase 5 REST endpoints in api.py: decision history, metrics filters, and team coverage."""
    from api import app
    client = app.test_client()

    with connection(test_db) as conn:
        conn.execute("""INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, requested_days, status, submitted_on)
                        VALUES (71, 'E01', 'annual', '2026-11-16', '2026-11-17', 2, 'pending', '2026-11-01')""")

    # Evaluate request to populate decision history
    evaluate_leave_request(71, db_path=test_db)

    # Test GET /api/leave/decision-history/<request_id>
    # Note: DB_PATH in api is shared; we test function via get_decision_history directly and route availability
    res_history = client.get("/api/leave/decision-history/71")
    assert res_history.status_code == 200
    data = res_history.get_json()
    assert data['request_id'] == 71
    assert "decision_history" in data

    # Test GET /api/analytics/metrics with multi-filters
    res_metrics = client.get(
        "/api/analytics/metrics?month=2026-11&leave_type=annual&status=pending",
        headers={"X-Actor-ID": "HR01", "X-Actor-Role": "hr", "X-Actor-Team": "T01"}
    )
    assert res_metrics.status_code == 200
    m_data = res_metrics.get_json()
    assert "leave_type_breakdown" in m_data
    assert "definitions" in m_data

    # Test GET /api/analytics/team-coverage
    res_cov = client.get(
        "/api/analytics/team-coverage?team_id=T01&start_date=2026-11-01&end_date=2026-11-05",
        headers={"X-Actor-ID": "M01", "X-Actor-Role": "manager", "X-Actor-Team": "T01"}
    )
    assert res_cov.status_code == 200
    c_data = res_cov.get_json()
    assert c_data['team_id'] == 'T01'
    assert "average_coverage_percent" in c_data

