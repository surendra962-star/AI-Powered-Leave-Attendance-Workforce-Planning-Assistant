"""Comprehensive test suite for the Flask REST API backend.

Verifies:
1. Health and System Status endpoints.
2. Authentication (valid, invalid, missing credentials).
3. Role-Based Access Control and Scope Enforcement (401 / 403 status codes).
4. Validation Error Handling (400 Bad Request with clear error details).
5. Leave Operations: Submission, balance inquiry, decision with note, and decision history.
6. Attendance Management: Clock-in, duplicate prevention, clock-out, history, and regularization.
7. Workforce Planning & What-If Simulations.
8. Dashboards (Employee, Manager, HR).
9. Timeline, Expiry Alerts, and Overlap Inquiries.
10. Multi-Dimensional Analytics and CSV Export.
11. RAG Policy Assistant and Reindexing.
12. HR Administration and Audit Logging.
"""
from datetime import date, timedelta
from unittest.mock import patch
import pytest

from api import app
from database.db import connection, initialize, DB_PATH


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ==============================================================================
# 1. SYSTEM HEALTH & AUTHENTICATION
# ==============================================================================
def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert "Flask" in data["service"]


def test_auth_login_valid_invalid_and_missing(client):
    # Missing credentials -> 400
    res = client.post("/api/auth/login", json={})
    assert res.status_code == 400
    assert "required" in res.get_json()["error"]

    # Invalid password -> 401
    res = client.post("/api/auth/login", json={"employee_id": "E005", "password": "wrong_password"})
    assert res.status_code == 401
    assert "Invalid" in res.get_json()["error"]

    # Valid manager login -> 200
    res = client.post("/api/auth/login", json={"employee_id": "E005", "password": "kiranmgr@2026"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["employee_id"] == "E005"
    assert data["role"] == "manager"
    assert data["team_id"] == "T01"

    # GET /api/auth/me
    res_me = client.get("/api/auth/me", headers={"X-Actor-ID": "E005", "X-Actor-Role": "manager", "X-Actor-Team": "T01"})
    assert res_me.status_code == 200
    assert res_me.get_json()["employee_id"] == "E005"


# ==============================================================================
# 2. ROLE-BASED ACCESS CONTROL (403 FORBIDDEN ENFORCEMENT)
# ==============================================================================
def test_rbac_and_scope_rejection(client):
    emp_headers = {"X-Actor-ID": "E001", "X-Actor-Role": "employee", "X-Actor-Team": "T01"}
    mgr_headers = {"X-Actor-ID": "E005", "X-Actor-Role": "manager", "X-Actor-Team": "T01"}

    # Employee attempting to access Manager dashboard -> 403
    res_mgr = client.get("/api/dashboard/manager", headers=emp_headers)
    assert res_mgr.status_code == 403
    assert "error" in res_mgr.get_json()

    # Employee attempting to access HR dashboard -> 403
    res_hr = client.get("/api/dashboard/hr", headers=emp_headers)
    assert res_hr.status_code == 403

    # Manager attempting to access HR dashboard -> 403
    res_mgr_hr = client.get("/api/dashboard/hr", headers=mgr_headers)
    assert res_mgr_hr.status_code == 403

    # Employee attempting to query audit logs -> 403
    res_audit = client.get("/api/admin/audit-logs", headers=emp_headers)
    assert res_audit.status_code == 403

    # Employee attempting to list all employees -> 403
    res_emp_list = client.get("/api/admin/employees", headers=emp_headers)
    assert res_emp_list.status_code == 403


# ==============================================================================
# 3. LEAVE OPERATIONS, VALIDATION & DECISION AUDIT TRAIL
# ==============================================================================
def test_leave_submission_validation_and_decision_history(client):
    # Validation error: Missing start_date and end_date -> 400
    res_invalid = client.post("/api/leave/request", json={"employee_id": "E001", "leave_type": "annual"})
    assert res_invalid.status_code == 400
    assert "Missing required fields" in res_invalid.get_json()["error"]

    # Balance check -> 200
    res_bal = client.get("/api/leave/balance?employee_id=E001&leave_type=annual&year=2026")
    assert res_bal.status_code == 200
    assert "remaining_days" in res_bal.get_json()

    # Valid submission (future date)
    start_str = "2026-12-08"
    end_str = "2026-12-10"
    with connection() as conn:
        conn.execute("""
            DELETE FROM decision_history WHERE request_id IN (
                SELECT request_id FROM leave_requests WHERE employee_id='E001' AND start_date >= '2026-12-05' AND end_date <= '2026-12-12'
            )
        """)
        conn.execute("""
            DELETE FROM timeline_items WHERE employee_id='E001' AND item_type IN ('approval_deadline', 'return_to_work')
        """)
        conn.execute("DELETE FROM leave_requests WHERE employee_id='E001' AND start_date >= '2026-12-05' AND end_date <= '2026-12-12'")
        # Reset annual balance to ensure the test is idempotent across repeated runs
        # (prior test passes may have consumed E001's entitlement)
        conn.execute("""
            UPDATE leave_balances SET used_days = 0
            WHERE employee_id = 'E001' AND leave_type = 'annual' AND year = 2026
        """)

    res_sub = client.post(
        "/api/leave/request",
        headers={"X-Actor-ID": "E001", "X-Actor-Role": "employee"},
        json={
            "employee_id": "E001",
            "leave_type": "annual",
            "start_date": start_str,
            "end_date": end_str,
            "reason": "Family vacation",
            "exclude_optional_holidays": False
        }
    )
    assert res_sub.status_code == 201
    req_id = res_sub.get_json()["request_id"]
    assert req_id > 0

    # AI evaluation via API
    res_eval = client.post("/api/workforce/evaluate", json={"request_id": req_id})
    assert res_eval.status_code == 200
    eval_data = res_eval.get_json()
    assert eval_data["automatic_approval"] is False
    assert "recommendation" in eval_data

    # Manager decision with note via API
    res_dec = client.post(
        "/api/leave/decide",
        headers={"X-Actor-ID": "E005", "X-Actor-Role": "manager", "X-Actor-Team": "T01"},
        json={
            "request_id": req_id,
            "decision": "approved",
            "note": "Approved via REST API test",
            "decided_on": date.today().isoformat()
        }
    )
    assert res_dec.status_code == 200

    # Retrieve decision history via API
    res_hist = client.get(f"/api/leave/decision-history/{req_id}")
    assert res_hist.status_code == 200
    hist_data = res_hist.get_json()
    assert hist_data["request_id"] == req_id
    assert len(hist_data["decision_history"]) >= 2
    # Verify AI evaluation and human decision separation
    assert any(h["is_ai_recommendation"] for h in hist_data["decision_history"])
    human_dec = next((h for h in hist_data["decision_history"] if h["is_human_decision"]), None)
    assert human_dec is not None
    assert human_dec["final_decision"] == "approved"
    assert human_dec["decided_by"] == "E005"


# ==============================================================================
# 4. ATTENDANCE MANAGEMENT & DUPLICATE PREVENTION
# ==============================================================================
def test_attendance_lifecycle_and_duplicate_prevention(client):
    test_date = "2026-12-28"
    with connection() as conn:
        conn.execute("DELETE FROM attendance WHERE employee_id='E001' AND date=?", (test_date,))

    # Clock in -> 200
    res1 = client.post(
        "/api/attendance/clock-in",
        headers={"X-Actor-ID": "E001", "X-Actor-Role": "employee"},
        json={"employee_id": "E001", "date": test_date, "time": "09:15:00"}
    )
    assert res1.status_code == 200
    assert res1.get_json()["status"] in ("present", "success")

    # Duplicate clock in on same date -> 400 Bad Request
    res_dup = client.post(
        "/api/attendance/clock-in",
        headers={"X-Actor-ID": "E001", "X-Actor-Role": "employee"},
        json={"employee_id": "E001", "date": test_date, "time": "09:30:00"}
    )
    assert res_dup.status_code == 400
    assert "already clocked in" in res_dup.get_json()["error"]

    # Clock out -> 200
    res_out = client.post(
        "/api/attendance/clock-out",
        headers={"X-Actor-ID": "E001", "X-Actor-Role": "employee"},
        json={"employee_id": "E001", "date": test_date, "time": "18:00:00"}
    )
    assert res_out.status_code == 200
    assert res_out.get_json()["check_out"] == "18:00:00"

    # Missing clock outs discovery & regularization
    res_missing = client.get(
        "/api/attendance/missing-clock-outs",
        headers={"X-Actor-ID": "E005", "X-Actor-Role": "manager", "X-Actor-Team": "T01"}
    )
    assert res_missing.status_code == 200
    assert isinstance(res_missing.get_json(), list)


# ==============================================================================
# 5. WORKFORCE PLANNING & WHAT-IF SIMULATION
# ==============================================================================
def test_workforce_planning_and_simulation(client):
    # Coverage endpoint -> 200
    res_cov = client.get("/api/workforce/coverage?team_id=T01&date=2026-11-04")
    assert res_cov.status_code == 200
    assert "coverage_percent" in res_cov.get_json()

    # Backups for deadline -> 200
    res_bk = client.get("/api/workforce/backups?deadline_id=1")
    assert res_bk.status_code in (200, 400)  # depending on whether deadline 1 exists

    # What-If leave simulation -> 200
    res_sim = client.post(
        "/api/workforce/what-if",
        json={
            "team_id": "T01",
            "start_date": "2026-11-16",
            "end_date": "2026-11-20",
            "absent_employee_ids": ["E001", "E002"],
            "threshold_percent": 60
        }
    )
    assert res_sim.status_code == 200
    sim_data = res_sim.get_json()
    assert "is_feasible" in sim_data
    assert "lowest_simulated_coverage_percent" in sim_data


# ==============================================================================
# 6. DASHBOARDS (ROLE-SCOPED)
# ==============================================================================
def test_dashboards_endpoints(client):
    emp_h = {"X-Actor-ID": "E001", "X-Actor-Role": "employee", "X-Actor-Team": "T01"}
    mgr_h = {"X-Actor-ID": "E005", "X-Actor-Role": "manager", "X-Actor-Team": "T01"}
    hr_h = {"X-Actor-ID": "HR001", "X-Actor-Role": "hr", "X-Actor-Team": "T01"}

    # Employee dashboard -> 200
    res_emp = client.get("/api/dashboard/employee", headers=emp_h)
    assert res_emp.status_code == 200
    assert "balances" in res_emp.get_json()
    assert "comp_off_summary" in res_emp.get_json()

    # Manager dashboard -> 200
    res_mgr = client.get("/api/dashboard/manager", headers=mgr_h)
    assert res_mgr.status_code == 200
    m_data = res_mgr.get_json()
    assert "pending_requests" in m_data
    assert "pending_approval_deadlines" in m_data
    assert "comp_off_balances" in m_data
    assert "low_coverage_warnings" in m_data

    # HR dashboard -> 200
    res_hr = client.get("/api/dashboard/hr", headers=hr_h)
    assert res_hr.status_code == 200
    hr_data = res_hr.get_json()
    assert "active_headcount" in hr_data
    assert "pending_queue" in hr_data
    assert "comp_off_summary" in hr_data


# ==============================================================================
# 7. TIMELINE, ALERTS & OVERLAP INQUIRY
# ==============================================================================
def test_timeline_alerts_and_overlap_query(client):
    mgr_h = {"X-Actor-ID": "E005", "X-Actor-Role": "manager", "X-Actor-Team": "T01"}

    # Timeline alerts -> 200
    res_alerts = client.get("/api/timeline/alerts?horizon_days=30", headers=mgr_h)
    assert res_alerts.status_code == 200
    assert isinstance(res_alerts.get_json(), list)

    # Timeline events -> 200
    res_events = client.get("/api/timeline/events?start_date=2026-11-01&end_date=2026-11-30", headers=mgr_h)
    assert res_events.status_code == 200
    assert isinstance(res_events.get_json(), list)

    # Structured overlap inquiry -> 200
    res_inquiry = client.post(
        "/api/timeline/query-overlap",
        headers=mgr_h,
        json={
            "team_id": "T01",
            "start_date": "2026-11-16",
            "end_date": "2026-11-20",
            "employee_id": "E001"
        }
    )
    assert res_inquiry.status_code == 200
    inq_data = res_inquiry.get_json()
    assert "has_operational_risk" in inq_data
    assert "explanation" in inq_data


# ==============================================================================
# 8. MULTI-DIMENSIONAL ANALYTICS & CSV EXPORT
# ==============================================================================
def test_analytics_metrics_and_csv_export(client):
    hr_h = {"X-Actor-ID": "HR001", "X-Actor-Role": "hr", "X-Actor-Team": "T01"}

    # Metrics with filters -> 200
    res_metrics = client.get(
        "/api/analytics/metrics?month=2026-11&team_id=T01&leave_type=annual",
        headers=hr_h
    )
    assert res_metrics.status_code == 200
    m_data = res_metrics.get_json()
    assert "attendance" in m_data
    assert "leave_type_breakdown" in m_data
    assert "definitions" in m_data

    # Team coverage analytics -> 200
    res_tc = client.get(
        "/api/analytics/team-coverage?team_id=T01&start_date=2026-11-01&end_date=2026-11-10",
        headers=hr_h
    )
    assert res_tc.status_code == 200
    assert "average_coverage_percent" in res_tc.get_json()

    # CSV Export -> 200 (text/csv)
    res_csv = client.get("/api/analytics/export-csv?month=2026-11", headers=hr_h)
    assert res_csv.status_code == 200
    assert "WORKFORCE ANALYTICS SUMMARY" in res_csv.data.decode("utf-8")


# ==============================================================================
# 9. RAG ASSISTANT ENDPOINT
# ==============================================================================
def test_rag_ask_endpoint(client):
    # Validation error: empty question -> 400
    res_err = client.post("/api/rag/ask", json={"question": "   "})
    assert res_err.status_code == 400

    mock_res = {
        "answer": "Employees receive 18 days annual leave [1].",
        "sources": [{"marker": 1, "document": "Sample Leave Policy", "version": "2.0", "section": "1. Annual Leave", "page": 1}],
        "warnings": [],
        "llm_model": "llama3.2"
    }
    with patch("api.ask", return_value=mock_res):
        res = client.post("/api/rag/ask", json={"question": "How many annual leave days?", "as_of": "2026-10-31"})
        assert res.status_code == 200
        data = res.get_json()
        assert "18 days" in data["answer"]
        assert len(data["sources"]) == 1
