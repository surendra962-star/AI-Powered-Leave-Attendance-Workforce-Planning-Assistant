"""Phase 6 end-to-end checks using an isolated synthetic SQLite database."""
from pathlib import Path
import pytest

from database.db import initialize, connection
from leave_management.service import create_leave_request, decide_leave_request, get_balance
from access_control.service import UserContext, AccessError, initialize_security
from dashboards.service import employee_dashboard, hr_dashboard


@pytest.fixture
def workflow_db(tmp_path: Path):
    db_path = tmp_path / "phase6_workflow.db"
    initialize(db_path)
    with connection(db_path) as conn:
        conn.execute("INSERT INTO teams VALUES ('T01','AI Development',60)")
        conn.executemany(
            """INSERT INTO employees
               (employee_id,name,email,role,team_id,manager_id,joined_on)
               VALUES (?,?,?,?,?,?,?)""",
            [
                ('M001', 'Mohan', 'mohan@example.test', 'manager', 'T01', None, '2025-01-01'),
                ('E001', 'Asha', 'asha@example.test', 'employee', 'T01', 'M001', '2025-01-01'),
                ('H001', 'HR Admin', 'hr@example.test', 'hr', 'T01', None, '2025-01-01'),
            ],
        )
        conn.execute("INSERT INTO leave_balances VALUES ('E001','annual',2026,18,2)")
    initialize_security(db_path)
    return db_path


def test_end_to_end_leave_request_approval_updates_balance_dashboard_and_audit(workflow_db):
    request_id = create_leave_request(
        'E001', 'annual', '2026-12-07', '2026-12-08',
        submitted_on='2026-11-30', db_path=workflow_db,
    )
    manager = UserContext('M001', 'Mohan', 'manager', 'T01')
    decide_leave_request(request_id, 'approved', 'M001', decided_on='2026-12-01', db_path=workflow_db)

    assert get_balance('E001', 'annual', 2026, workflow_db)['remaining_days'] == 14
    employee = UserContext('E001', 'Asha', 'employee', 'T01')
    dashboard = employee_dashboard(employee, workflow_db)
    assert dashboard['leave_requests'][0]['status'] == 'approved'

    with connection(workflow_db) as conn:
        audit = conn.execute(
            "SELECT final_decision,decided_by FROM decision_history WHERE request_id=?",
            (request_id,),
        ).fetchone()
    assert tuple(audit) == ('approved', 'M001')


def test_employee_cannot_open_hr_dashboard(workflow_db):
    employee = UserContext('E001', 'Asha', 'employee', 'T01')
    with pytest.raises(AccessError):
        hr_dashboard(employee, workflow_db)


def test_phase1_to_phase5_business_tables_are_present(workflow_db):
    expected = {
        'teams', 'employees', 'policy_documents', 'leave_balances', 'holidays',
        'leave_requests', 'attendance', 'comp_off_records', 'project_deadlines',
        'backup_assignments', 'decision_history', 'user_credentials', 'timeline_items',
    }
    with connection(workflow_db) as conn:
        actual = {row['name'] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert expected <= actual
