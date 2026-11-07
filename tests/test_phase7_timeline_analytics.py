from pathlib import Path
import pytest
from database.db import initialize, connection
from access_control.service import UserContext
from timeline.service import add_timeline_item, list_timeline, get_alerts, comp_off_summary
from analytics.service import workforce_metrics
from leave_management.service import decide_leave_request, LeaveError

@pytest.fixture
def db(tmp_path):
    p=tmp_path/'p7.db'; initialize(p)
    with connection(p) as c:
        c.execute("INSERT INTO teams VALUES ('T1','Team One',60)")
        c.executemany("INSERT INTO employees(employee_id,name,email,role,team_id,manager_id,joined_on) VALUES(?,?,?,?,?,?,?)",[
          ('M1','Manager','m@x.test','manager','T1',None,'2025-01-01'),
          ('E1','Employee','e@x.test','employee','T1','M1','2025-01-01'),
          ('E2','Other','e2@x.test','employee','T1','M1','2025-01-01'),
          ('H1','HR','h@x.test','hr','T1',None,'2025-01-01')])
        c.execute("INSERT INTO leave_requests(employee_id,leave_type,start_date,end_date,requested_days,status,submitted_on,approval_due_on) VALUES('E1','annual','2026-12-10','2026-12-10',1,'pending','2026-12-01','2026-12-03')")
        c.execute("INSERT INTO comp_off_records(employee_id,earned_on,expires_on,days,status) VALUES('E1','2026-11-01','2026-12-10',1,'available')")
        c.execute("INSERT INTO attendance(employee_id,date,status) VALUES('E1','2026-12-01','present')")
    return p

def test_timeline_role_scope_and_alerts(db):
    mgr=UserContext('M1','Manager','manager','T1'); emp=UserContext('E1','Employee','employee','T1')
    add_timeline_item(mgr,'Release','2026-12-12','project_deadline',db_path=db)
    assert len(list_timeline(emp,'2026-12-01','2026-12-31',db_path=db))==1
    assert any(a['type']=='approval_overdue' for a in get_alerts(emp,'2026-12-05',30,db))
    assert any(a['type']=='comp_off_expiry' for a in get_alerts(emp,'2026-12-05',30,db))
    with connection(db) as c:
        c.execute("INSERT INTO teams VALUES ('T2','Other',60)")
        c.execute("INSERT INTO employees(employee_id,name,email,role,team_id,joined_on) VALUES('X1','External','x@x.test','employee','T2','2025-01-01')")
    with pytest.raises(PermissionError): add_timeline_item(mgr,'Other','2026-12-12','other','X1',db_path=db)

def test_comp_off_summary_and_analytics_definition(db):
    emp=UserContext('E1','Employee','employee','T1')
    assert comp_off_summary(emp,as_of='2026-12-05',db_path=db)['available_days']==1
    result=workforce_metrics(emp,'2026-12',db_path=db)
    assert result['attendance']['attendance_percent']==100
    assert 'Approved leave is excluded' in result['definitions']['attendance_percent']

def test_manager_cannot_decide_other_team_request(db):
    with connection(db) as c:
        c.execute("INSERT INTO teams VALUES ('T2','Other Team',60)")
        c.execute("INSERT INTO employees(employee_id,name,email,role,team_id,joined_on) VALUES('M2','Manager2','m2@x.test','manager','T2','2025-01-01')")
        c.execute("INSERT INTO employees(employee_id,name,email,role,team_id,manager_id,joined_on) VALUES('E3','Outsider','e3@x.test','employee','T2','M2','2025-01-01')")
        c.execute("INSERT INTO leave_requests(employee_id,leave_type,start_date,end_date,requested_days,status,submitted_on) VALUES('E3','sick','2026-12-10','2026-12-10',1,'pending','2026-12-01')")
        rid=c.execute('SELECT MAX(request_id) FROM leave_requests').fetchone()[0]
    with pytest.raises(LeaveError,match='own team'):
        decide_leave_request(rid,'declined','M1',db_path=db)

def test_manager_can_record_comp_off_only_for_own_team(db):
    from timeline.service import record_comp_off
    mgr=UserContext('M1','Manager','manager','T1')
    rid=record_comp_off(mgr,'E1','2026-12-01','2027-02-01',1.5,db)
    assert rid > 0
    with connection(db) as c:
        c.execute("INSERT INTO teams VALUES ('T2','Other',60)")
        c.execute("INSERT INTO employees(employee_id,name,email,role,team_id,joined_on) VALUES('X1','External','x@x.test','employee','T2','2025-01-01')")
    with pytest.raises(PermissionError): record_comp_off(mgr,'X1','2026-12-01','2027-02-01',1,db)
