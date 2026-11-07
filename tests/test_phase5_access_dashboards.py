from pathlib import Path
import pytest
from database.db import initialize, connection
from access_control.service import (AccessError, UserContext, authenticate,
    bootstrap_hr, initialize_security, set_employee_password, require_role)
from dashboards.service import employee_dashboard, manager_dashboard, hr_dashboard, list_employee_leave

@pytest.fixture
def db(tmp_path: Path):
    path = tmp_path / 'phase5.db'
    initialize(path)
    with connection(path) as conn:
        conn.execute("INSERT INTO teams VALUES ('T01','AI Development',60)")
        conn.executemany("""INSERT INTO employees(employee_id,name,email,role,team_id,manager_id,joined_on)
            VALUES(?,?,?,?,?,?,?)""", [
            ('E002','Mohan','mohan@example.test','manager','T01',None,'2025-01-01'),
            ('E001','Asha','asha@example.test','employee','T01','E002','2025-01-01'),
            ('E003','HR User','hr@example.test','hr','T01',None,'2025-01-01'),
        ])
        conn.execute("INSERT INTO leave_balances VALUES ('E001','annual',2026,18,2)")
        conn.execute("""INSERT INTO leave_requests(employee_id,leave_type,start_date,end_date,requested_days,status,submitted_on)
            VALUES('E001','annual','2026-12-01','2026-12-02',2,'pending','2026-11-01')""")
        conn.execute("INSERT INTO attendance(employee_id,date,status) VALUES('E001','2026-10-01','present')")
    initialize_security(path)
    return path

def test_bootstrap_and_authenticate(db):
    bootstrap_hr('E003','a-long-secure-password',db)
    hr = authenticate('E003','a-long-secure-password',db)
    assert hr.role == 'hr'
    with pytest.raises(AccessError): authenticate('E003','wrong-password',db)
    with pytest.raises(AccessError): bootstrap_hr('E003','another-long-password',db)

def test_hr_can_provision_employee_and_manager(db):
    bootstrap_hr('E003','a-long-secure-password',db)
    hr = authenticate('E003','a-long-secure-password',db)
    set_employee_password(hr,'E001','employee-password-1',db)
    assert authenticate('E001','employee-password-1',db).role == 'employee'
    with pytest.raises(AccessError): set_employee_password(authenticate('E001','employee-password-1',db),'E002','manager-password-1',db)

def test_employee_dashboard_is_self_scoped(db):
    employee = UserContext('E001','Asha','employee','T01')
    data = employee_dashboard(employee,db)
    assert data['balances'][0]['remaining_days'] == 16
    assert data['leave_requests'][0]['status'] == 'pending'
    with pytest.raises(AccessError): list_employee_leave(employee,'E002',db)

def test_manager_dashboard_is_team_scoped(db):
    manager = UserContext('E002','Mohan','manager','T01')
    data = manager_dashboard(manager,db)
    assert data['team']['active_headcount'] == 3
    assert data['pending_requests'][0]['employee_id'] == 'E001'
    with pytest.raises(AccessError): hr_dashboard(manager,db)

def test_hr_dashboard_is_org_wide_and_employee_cannot_open_it(db):
    bootstrap_hr('E003','a-long-secure-password',db)
    hr = authenticate('E003','a-long-secure-password',db)
    assert hr_dashboard(hr,db)['active_headcount'] == 3
    with pytest.raises(AccessError): hr_dashboard(UserContext('E001','Asha','employee','T01'),db)

def test_manager_can_read_same_team_employee_but_employee_cannot_read_peer(db):
    manager = UserContext('E002','Mohan','manager','T01')
    employee = UserContext('E001','Asha','employee','T01')
    assert len(list_employee_leave(manager,'E001',db)) == 1
    with pytest.raises(AccessError): list_employee_leave(employee,'E002',db)
