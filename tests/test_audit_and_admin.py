"""Tests for HR employee administration and audit logging."""
from pathlib import Path
import pytest
from database.db import initialize, connection, log_audit
from access_control.service import (
    UserContext, AccessError, initialize_security,
    create_employee, deactivate_employee, list_all_employees, get_audit_logs
)

@pytest.fixture
def db(tmp_path: Path):
    path = tmp_path / 'admin_test.db'
    initialize(path)
    with connection(path) as conn:
        conn.execute("INSERT INTO teams VALUES ('T01','AI Development',60)")
        conn.executemany("""INSERT INTO employees(employee_id,name,email,role,team_id,manager_id,joined_on)
            VALUES(?,?,?,?,?,?,?)""", [
            ('HR01','HR Admin','hr@test.com','hr','T01',None,'2025-01-01'),
            ('M01','Manager One','m1@test.com','manager','T01',None,'2025-01-01'),
            ('E01','Employee One','e1@test.com','employee','T01','M01','2025-01-01'),
        ])
    initialize_security(path)
    return path


def test_hr_can_create_and_deactivate_employee(db):
    hr = UserContext('HR01', 'HR Admin', 'hr', 'T01')
    
    # Create employee
    emp_data = create_employee(
        hr,
        employee_id='E99',
        name='New Hire',
        email='newhire@test.com',
        role='employee',
        team_id='T01',
        manager_id='M01',
        joined_on='2026-10-01',
        db_path=db
    )
    assert emp_data['employee_id'] == 'E99'
    
    # Verify in list
    all_emps = list_all_employees(hr, db_path=db)
    emp_ids = [e['employee_id'] for e in all_emps]
    assert 'E99' in emp_ids
    
    # Deactivate employee
    deactivated = deactivate_employee(hr, 'E99', db_path=db)
    assert deactivated['is_active'] == 0
    
    # Non-HR cannot create or deactivate
    emp = UserContext('E01', 'Employee One', 'employee', 'T01')
    with pytest.raises(AccessError):
        create_employee(emp, 'E100', 'Fail', 'fail@test.com', 'employee', 'T01', db_path=db)
    with pytest.raises(AccessError):
        deactivate_employee(emp, 'E99', db_path=db)


def test_audit_logs_recorded_and_retrieved(db):
    hr = UserContext('HR01', 'HR Admin', 'hr', 'T01')
    
    # Log custom event
    log_audit('HR01', 'hr', 'policy_update', 'POL01', 'Updated leave policy', db_path=db)
    
    # Retrieve logs
    logs = get_audit_logs(hr, limit=50, db_path=db)
    assert len(logs) >= 1
    actions = [log['action'] for log in logs]
    assert 'policy_update' in actions
    
    # Non-HR cannot view audit logs
    emp = UserContext('E01', 'Employee One', 'employee', 'T01')
    with pytest.raises(AccessError):
        get_audit_logs(emp, db_path=db)
