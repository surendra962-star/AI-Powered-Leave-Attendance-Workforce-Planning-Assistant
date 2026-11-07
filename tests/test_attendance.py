"""Unit and integration tests for attendance module."""
from datetime import date
from pathlib import Path
import pytest
from database.db import initialize, connection
from access_control.service import UserContext, AccessError, initialize_security
from attendance.service import (
    record_attendance, clock_in, clock_out,
    get_employee_attendance, get_team_attendance,
    get_hr_attendance_overview, get_monthly_attendance_summary,
    export_attendance_csv
)

@pytest.fixture
def db(tmp_path: Path):
    path = tmp_path / 'att_test.db'
    initialize(path)
    with connection(path) as conn:
        conn.execute("INSERT INTO teams VALUES ('T01','AI Development',60)")
        conn.execute("INSERT INTO teams VALUES ('T02','Data Engineering',50)")
        conn.executemany("""INSERT INTO employees(employee_id,name,email,role,team_id,manager_id,joined_on)
            VALUES(?,?,?,?,?,?,?)""", [
            ('M01','Manager One','m1@test.com','manager','T01',None,'2025-01-01'),
            ('E01','Employee One','e1@test.com','employee','T01','M01','2025-01-01'),
            ('E02','Employee Two','e2@test.com','employee','T01','M01','2025-01-01'),
            ('HR01','HR Admin','hr@test.com','hr','T01',None,'2025-01-01'),
        ])
    initialize_security(path)
    return path


def test_clock_in_and_clock_out(db):
    emp = UserContext('E01', 'Employee One', 'employee', 'T01')
    today_str = date.today().isoformat()
    
    # Clock in
    rec1 = clock_in(emp, 'E01', db_path=db)
    assert rec1['status'] == 'present'
    assert rec1['check_in'] is not None
    assert rec1['date'] == today_str
    
    # Clock out
    rec2 = clock_out(emp, 'E01', db_path=db)
    assert rec2['check_out'] is not None
    assert rec2['check_in'] == rec1['check_in']
    
    # Attendance retrieval
    history = get_employee_attendance(emp, 'E01', db_path=db)
    assert len(history) == 1
    assert history[0]['status'] == 'present'


def test_duplicate_attendance_updates_safely(db):
    hr = UserContext('HR01', 'HR Admin', 'hr', 'T01')
    # Record initial
    record_attendance(hr, 'E01', '2026-10-15', 'absent', db_path=db)
    summary = get_monthly_attendance_summary(hr, '2026-10', employee_id='E01', db_path=db)
    assert summary['absent'] == 1
    assert summary['present'] == 0
    
    # Update to present
    record_attendance(hr, 'E01', '2026-10-15', 'present', check_in="09:00:00", check_out="17:00:00", db_path=db)
    summary2 = get_monthly_attendance_summary(hr, '2026-10', employee_id='E01', db_path=db)
    assert summary2['absent'] == 0
    assert summary2['present'] == 1
    assert summary2['attendance_percentage'] == 100.0


def test_attendance_rbac_isolation(db):
    emp1 = UserContext('E01', 'Employee One', 'employee', 'T01')
    emp2 = UserContext('E02', 'Employee Two', 'employee', 'T01')
    
    # Employee cannot clock in for peer
    with pytest.raises(AccessError):
        clock_in(emp1, 'E02', db_path=db)
        
    # Employee cannot view peer's attendance
    with pytest.raises(AccessError):
        get_employee_attendance(emp1, 'E02', db_path=db)


def test_manager_team_attendance_and_hr_overview(db):
    mgr = UserContext('M01', 'Manager One', 'manager', 'T01')
    hr = UserContext('HR01', 'HR Admin', 'hr', 'T01')
    
    # Record attendance for two employees
    record_attendance(mgr, 'E01', '2026-10-10', 'present', db_path=db)
    record_attendance(mgr, 'E02', '2026-10-10', 'absent', db_path=db)
    
    # Manager views team attendance
    team_att = get_team_attendance(mgr, 'T01', date_str='2026-10-10', db_path=db)
    assert len(team_att) >= 2
    statuses = {r['employee_id']: r['status'] for r in team_att}
    assert statuses['E01'] == 'present'
    assert statuses['E02'] == 'absent'
    
    # HR views org overview
    overview = get_hr_attendance_overview(hr, date_str='2026-10-10', db_path=db)
    assert overview['present_count'] == 1
    assert overview['absent_count'] == 1
    assert len(overview['records']) >= 2
    
    # Export CSV
    csv_data = export_attendance_csv(hr, db_path=db)
    assert "Employee ID" in csv_data or "employee_id" in csv_data.lower()
    assert "E01" in csv_data
    assert "present" in csv_data
