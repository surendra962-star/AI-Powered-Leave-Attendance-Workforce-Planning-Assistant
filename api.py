"""Flask REST API backend for the AI-Powered Leave, Attendance & Workforce Planning Assistant."""
from __future__ import annotations
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from flask import Flask, request, jsonify

from access_control.service import (
    authenticate, AccessError, UserContext, initialize_security,
    create_employee, deactivate_employee, list_all_employees, get_audit_logs,
    set_employee_password
)
from leave_management.service import (
    create_leave_request, decide_leave_request, cancel_leave_request,
    get_balance, list_leave_requests, list_holidays, refresh_comp_off_status,
    get_calendar_breakdown, explain_leave_interaction,
    LeaveError
)
from attendance.service import (
    clock_in, clock_out, get_employee_attendance, get_team_attendance,
    get_hr_attendance_overview, get_monthly_attendance_summary,
    get_missing_clock_outs, regularize_missing_clock_out, AttendanceError
)
from workforce_planning.service import (
    evaluate_leave_request, team_coverage, recommend_backups,
    team_capacity_forecast, list_team_deadlines
)
from dashboards.service import employee_dashboard, manager_dashboard, hr_dashboard, get_decision_history
from timeline.service import (
    get_alerts, list_timeline, add_timeline_item, comp_off_summary, record_comp_off,
    query_timeline_overlap, calculate_return_to_work_date
)
from analytics.service import (
    workforce_metrics, organization_workforce_summary,
    get_team_coverage_analytics, export_metrics_csv
)
from rag.assistant import ask
from rag.policies import load_policies
from rag.chunks import split_policy
from rag.store import rebuild
from database.db import initialize, DB_PATH, connection
from config import FLASK_HOST, FLASK_PORT, OLLAMA_MODEL

app = Flask(__name__)
app.config["ALLOW_TEST_HEADERS"] = False
initialize()
initialize_security()

SESSION_LIFETIME = timedelta(hours=8)
_API_SESSIONS: Dict[str, tuple] = {}


@app.errorhandler(AccessError)
def handle_access_error(error):
    return jsonify({"error": str(error)}), 401


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception("Unhandled API exception")
    return jsonify({"error": "Internal server error"}), 500


def _load_actor_from_database(employee_id: str) -> UserContext:
    from database.db import connection
    with connection() as conn:
        row = conn.execute(
            "SELECT employee_id,name,role,team_id,is_active FROM employees WHERE employee_id=?",
            (employee_id,),
        ).fetchone()
    if row is None or not row["is_active"]:
        raise AccessError("Authenticated account is inactive or unknown.")
    return UserContext(
        employee_id=row["employee_id"],
        name=row["name"],
        role=row["role"],
        team_id=row["team_id"],
    )


def _resolve_actor(data: Optional[dict] = None) -> UserContext:
    """Extract authenticated actor context from request headers, query params, or body."""
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        session = _API_SESSIONS.get(token)
        if session is None:
            raise AccessError("Invalid or expired access token.")
        actor, expires_at = session
        if datetime.now(timezone.utc) >= expires_at:
            _API_SESSIONS.pop(token, None)
            raise AccessError("Invalid or expired access token.")
        return actor

    # Development/test compatibility only. Never enabled by the API entrypoint.
    if app.config.get("ALLOW_TEST_HEADERS", False) or app.config.get("TESTING", False):
        actor_id = (
            request.headers.get("X-Actor-ID")
            or request.args.get("actor_id")
            or request.args.get("employee_id")
            or (data or {}).get("employee_id")
        )
        if actor_id:
            try:
                return _load_actor_from_database(actor_id.strip())
            except AccessError:
                # Legacy test clients may use synthetic IDs not present in the database.
                # This path is disabled outside Flask TESTING mode.
                return UserContext(
                    employee_id=actor_id.strip(),
                    name=actor_id.strip(),
                    role=request.headers.get("X-Actor-Role", "employee").strip(),
                    team_id=request.headers.get("X-Actor-Team") or None,
                )

    raise AccessError("Authentication required. Provide a Bearer access token.")


# ==============================================================================
# 1. SYSTEM HEALTH
# ==============================================================================
@app.route("/api/health", methods=["GET"])
def health():
    try:
        with connection() as conn:
            conn.execute("SELECT 1 FROM employees LIMIT 1").fetchone()
        status = "healthy"
        status_code = 200
    except Exception as exc:
        status = "degraded"
        status_code = 503
    return jsonify({
        "status": status,
        "service": "AI HR Assistant Flask Backend",
        "database_initialized": status == "healthy",
    }), status_code


# ==============================================================================
# 2. AUTHENTICATION & ACCESS CONTROL
# ==============================================================================
@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    employee_id = data.get("employee_id")
    password = data.get("password")
    if not employee_id or not password:
        return jsonify({"error": "employee_id and password are required"}), 400
    try:
        user = authenticate(employee_id.strip(), password)
        token = secrets.token_urlsafe(32)
        _API_SESSIONS[token] = (user, datetime.now(timezone.utc) + SESSION_LIFETIME)
        return jsonify({
            "employee_id": user.employee_id,
            "name": user.name,
            "role": user.role,
            "team_id": user.team_id,
            "access_token": token
        }), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/me", methods=["GET"])
def get_current_user():
    try:
        actor = _resolve_actor()
    except AccessError as e:
        return jsonify({"error": str(e)}), 401
    return jsonify({
        "employee_id": actor.employee_id,
        "name": actor.name,
        "role": actor.role,
        "team_id": actor.team_id
    }), 200


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        _API_SESSIONS.pop(authorization[7:].strip(), None)
    return jsonify({"status": "logged_out"}), 200



# ==============================================================================
# 3. LEAVE MANAGEMENT
# ==============================================================================
@app.route("/api/leave/request", methods=["POST"])
def submit_leave():
    data = request.get_json(force=True, silent=True) or {}
    try:
        actor = _resolve_actor(data)
    except AccessError as e:
        return jsonify({"error": str(e)}), 401
    employee_id = data.get("employee_id")
    leave_type = data.get("leave_type")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    reason = data.get("reason", "")
    submitted_on = data.get("submitted_on", date.today().isoformat())
    exclude_optional_holidays = bool(data.get("exclude_optional_holidays", False))

    if not all([employee_id, leave_type, start_date, end_date]):
        return jsonify({"error": "Missing required fields: employee_id, leave_type, start_date, end_date"}), 400
    if actor.role == "employee" and employee_id != actor.employee_id:
        return jsonify({"error": "Employees may submit leave only for their own account."}), 403
    if actor.role != "employee":
        return jsonify({"error": "Only employee accounts may submit leave requests."}), 403

    try:
        req_id = create_leave_request(
            employee_id=employee_id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            submitted_on=submitted_on,
            exclude_optional_holidays=exclude_optional_holidays
        )
        return jsonify({
            "message": "Leave request submitted successfully",
            "request_id": req_id
        }), 201
    except (LeaveError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/balance", methods=["GET"])
def check_balance():
    try:
        actor = _resolve_actor()
    except AccessError as e:
        return jsonify({"error": str(e)}), 401
    employee_id = request.args.get("employee_id")
    leave_type = request.args.get("leave_type", "annual")
    year = int(request.args.get("year", date.today().year))

    if not employee_id:
        return jsonify({"error": "employee_id query parameter is required"}), 400
    if actor.role == "employee" and employee_id != actor.employee_id:
        return jsonify({"error": "Employees may inspect only their own leave balance."}), 403
    if actor.role == "manager":
        from access_control.service import require_employee_scope
        try:
            require_employee_scope(actor, employee_id)
        except AccessError as e:
            return jsonify({"error": str(e)}), 403

    try:
        bal = get_balance(employee_id, leave_type, year)
        return jsonify(bal), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/requests", methods=["GET"])
def get_leave_requests():
    actor = _resolve_actor()
    target_emp = request.args.get("employee_id")
    try:
        records = list_leave_requests(actor, employee_id=target_emp)
        return jsonify(records), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/decide", methods=["POST"])
def record_decision():
    data = request.get_json(force=True, silent=True) or {}
    actor = _resolve_actor(data)
    request_id = data.get("request_id")
    decision = data.get("decision")  # approved or declined
    note = data.get("note", "")
    decided_on = data.get("decided_on", date.today().isoformat())

    if not request_id or not decision:
        return jsonify({"error": "request_id and decision ('approved'/'declined') are required"}), 400

    try:
        res = decide_leave_request(actor, request_id, decision, note=note, decided_on=decided_on)
        return jsonify(res), 200
    except (AccessError, LeaveError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/cancel", methods=["POST"])
def cancel_leave():
    data = request.get_json(force=True, silent=True) or {}
    actor = _resolve_actor(data)
    request_id = data.get("request_id")
    reason = data.get("reason", "")

    if not request_id:
        return jsonify({"error": "request_id is required"}), 400

    try:
        res = cancel_leave_request(actor, int(request_id), reason=reason)
        return jsonify(res), 200
    except (AccessError, LeaveError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/holidays", methods=["GET"])
def get_holidays():
    start_date = request.args.get("start_date", f"{date.today().year}-01-01")
    end_date = request.args.get("end_date", f"{date.today().year}-12-31")
    try:
        holidays = list_holidays(start_date, end_date)
        return jsonify(holidays), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/calendar-breakdown", methods=["GET"])
def handle_calendar_breakdown():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    exclude_optional = request.args.get("exclude_optional", "false").lower() in ("true", "1", "yes")
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400
    try:
        breakdown = get_calendar_breakdown(start_date, end_date, exclude_optional_holidays=exclude_optional)
        return jsonify(breakdown), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/explain-interaction", methods=["POST"])
def handle_explain_interaction():
    data = request.get_json(force=True, silent=True) or {}
    leave_type = data.get("leave_type", "annual")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    employee_id = data.get("employee_id")
    exclude_optional = bool(data.get("exclude_optional_holidays", False))

    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400
    try:
        explanation = explain_leave_interaction(
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            employee_id=employee_id,
            exclude_optional_holidays=exclude_optional
        )
        return jsonify(explanation), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leave/decision-history/<int:request_id>", methods=["GET"])
def get_leave_decision_history(request_id: int):
    try:
        history = get_decision_history(request_id)
        return jsonify({
            "request_id": request_id,
            "decision_history": history,
            "count": len(history)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ==============================================================================
# 4. ATTENDANCE MANAGEMENT
# ==============================================================================
@app.route("/api/attendance/clock-in", methods=["POST"])
def handle_clock_in():
    data = request.get_json(force=True, silent=True) or {}
    employee_id = data.get("employee_id")
    on_date = data.get("date", date.today().isoformat())
    time_str = data.get("time")

    if not employee_id:
        return jsonify({"error": "employee_id is required"}), 400

    try:
        actor = _resolve_actor(data)
        res = clock_in(actor, employee_id=employee_id, att_date=on_date, time_str=time_str)
        return jsonify(res), 200
    except (AttendanceError, AccessError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/attendance/clock-out", methods=["POST"])
def handle_clock_out():
    data = request.get_json(force=True, silent=True) or {}
    employee_id = data.get("employee_id")
    on_date = data.get("date", date.today().isoformat())
    time_str = data.get("time")

    if not employee_id:
        return jsonify({"error": "employee_id is required"}), 400

    try:
        actor = _resolve_actor(data)
        res = clock_out(actor, employee_id=employee_id, att_date=on_date, time_str=time_str)
        return jsonify(res), 200
    except (AttendanceError, AccessError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/attendance/history", methods=["GET"])
def get_attendance_history():
    actor = _resolve_actor()
    target_emp = request.args.get("employee_id", actor.employee_id)
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    try:
        history = get_employee_attendance(actor, target_emp, month=month)
        summary = get_monthly_attendance_summary(actor, target_emp, month=month)
        return jsonify({"history": history, "summary": summary}), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/attendance/missing-clock-outs", methods=["GET"])
def handle_missing_clock_outs():
    actor = _resolve_actor()
    before_date = request.args.get("before_date")
    emp_id = request.args.get("employee_id")
    team_id = request.args.get("team_id")
    try:
        records = get_missing_clock_outs(actor, before_date=before_date, employee_id=emp_id, team_id=team_id)
        return jsonify(records), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/attendance/regularize", methods=["POST"])
def handle_regularize_clock_out():
    data = request.get_json(force=True, silent=True) or {}
    employee_id = data.get("employee_id")
    att_date = data.get("date")
    check_out = data.get("check_out", "17:00:00")
    note = data.get("note", "Regularized missing clock-out")

    if not employee_id or not att_date:
        return jsonify({"error": "employee_id and date are required"}), 400

    try:
        actor = _resolve_actor(data)
        res = regularize_missing_clock_out(actor, employee_id=employee_id, attendance_date=att_date, default_check_out=check_out, note=note)
        return jsonify(res), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# 5. WORKFORCE PLANNING & DECISION SUPPORT
# ==============================================================================
@app.route("/api/workforce/evaluate", methods=["POST"])
def evaluate_request():
    data = request.get_json(force=True, silent=True) or {}
    request_id = data.get("request_id")
    if not request_id:
        return jsonify({"error": "request_id is required"}), 400
    try:
        res = evaluate_leave_request(int(request_id))
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/workforce/coverage", methods=["GET"])
def get_team_coverage():
    team_id = request.args.get("team_id", "T01")
    on_date = request.args.get("date", date.today().isoformat())
    try:
        res = team_coverage(team_id, on_date)
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/workforce/backups", methods=["GET"])
def get_backup_recommendations():
    deadline_id = request.args.get("deadline_id")
    if not deadline_id:
        return jsonify({"error": "deadline_id query parameter is required"}), 400
    try:
        recs = recommend_backups(int(deadline_id))
        return jsonify(recs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500




# ==============================================================================
# 6. DASHBOARDS (ROLE-SCOPED)
# ==============================================================================
@app.route("/api/dashboard/employee", methods=["GET"])
def get_employee_dashboard():
    actor = _resolve_actor()
    try:
        data = employee_dashboard(actor)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/manager", methods=["GET"])
def get_manager_dashboard():
    actor = _resolve_actor()
    try:
        requested_team = request.args.get("team_id")
        if actor.role == "manager" and requested_team and requested_team != actor.team_id:
            raise AccessError("Managers cannot access another team's dashboard.")
        data = manager_dashboard(actor)
        return jsonify(data), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/hr", methods=["GET"])
def get_hr_dashboard():
    actor = _resolve_actor()
    try:
        data = hr_dashboard(actor)
        return jsonify(data), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# 7. TIMELINE & COMP-OFF
# ==============================================================================
@app.route("/api/timeline/alerts", methods=["GET"])
def get_timeline_alerts():
    actor = _resolve_actor()
    horizon = int(request.args.get("horizon_days", 30))
    try:
        alerts = get_alerts(actor, horizon_days=horizon)
        return jsonify(alerts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/timeline/events", methods=["GET"])
def get_timeline_events():
    actor = _resolve_actor()
    start_date = request.args.get("start_date", date.today().isoformat())
    end_date = request.args.get("end_date", (date.today()).isoformat())
    try:
        events = list_timeline(actor, start_date, end_date)
        return jsonify(events), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/timeline/query-overlap", methods=["POST"])
def handle_timeline_overlap():
    actor = _resolve_actor()
    data = request.get_json(force=True, silent=True) or {}
    team_id = data.get("team_id", actor.team_id or "T01")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    employee_id = data.get("employee_id", actor.employee_id)

    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    try:
        res = query_timeline_overlap(actor, team_id, start_date, end_date, employee_id=employee_id)
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/compoff/summary", methods=["GET"])
def get_compoff_summary():
    actor = _resolve_actor()
    emp_id = request.args.get("employee_id", actor.employee_id)
    try:
        summary = comp_off_summary(actor, emp_id)
        return jsonify(summary), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# 8. WORKFORCE ANALYTICS
# ==============================================================================
@app.route("/api/analytics/metrics", methods=["GET"])
def get_analytics():
    actor = _resolve_actor()
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    team_id = request.args.get("team_id")
    employee_id = request.args.get("employee_id")
    leave_type = request.args.get("leave_type")
    status = request.args.get("status")
    try:
        metrics = workforce_metrics(
            actor,
            month=month,
            team_id=team_id,
            employee_id=employee_id,
            leave_type=leave_type,
            status=status
        )
        return jsonify(metrics), 200
    except (AccessError, PermissionError) as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analytics/team-coverage", methods=["GET"])
def get_team_coverage_route():
    actor = _resolve_actor()
    team_id = request.args.get("team_id", actor.team_id or "T01")
    start_date = request.args.get("start_date", date.today().isoformat())
    end_date = request.args.get("end_date")
    if not end_date:
        return jsonify({"error": "end_date is required"}), 400
    try:
        cov = get_team_coverage_analytics(actor, team_id, start_date, end_date)
        return jsonify(cov), 200
    except (AccessError, PermissionError) as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analytics/organization", methods=["GET"])
def get_org_analytics():
    actor = _resolve_actor()
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    try:
        summary = organization_workforce_summary(actor, month=month)
        return jsonify(summary), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analytics/export-csv", methods=["GET"])
def export_analytics_csv_route():
    actor = _resolve_actor()
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    team_id = request.args.get("team_id")
    try:
        csv_text = export_metrics_csv(actor, month=month, team_id=team_id)
        from flask import Response
        return Response(csv_text, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=workforce_{month}.csv"})
    except (AccessError, PermissionError) as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ==============================================================================
# 9. HR POLICY ASSISTANT (RAG)
# ==============================================================================
@app.route("/api/rag/ask", methods=["POST"])
def handle_rag_ask():
    data = request.get_json(force=True, silent=True) or {}
    question = data.get("question")
    as_of = data.get("as_of")
    llm_model = data.get("llm_model", OLLAMA_MODEL)

    if not question or not question.strip():
        return jsonify({"error": "question field is required and must not be empty"}), 400

    on_date = date.fromisoformat(as_of) if as_of else date.today()
    try:
        result = ask(question.strip(), on=on_date, llm_model=llm_model)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rag/reindex", methods=["POST"])
def handle_reindex():
    try:
        policies = load_policies()
        chunks = [c for p in policies for c in split_policy(p)]
        indexed_count = rebuild(chunks, DB_PATH.parent / "chroma")
        return jsonify({
            "status": "success",
            "indexed_chunks": indexed_count,
            "policies_count": len(policies)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# 10. HR ADMINISTRATION & AUDIT LOGS
# ==============================================================================
@app.route("/api/admin/employees", methods=["GET"])
def get_all_employees():
    actor = _resolve_actor()
    try:
        from access_control.service import require_role
        require_role(actor, "hr")
        employees = list_all_employees(actor)
        return jsonify(employees), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/create-employee", methods=["POST"])
def admin_create_employee():
    actor = _resolve_actor()
    data = request.get_json(force=True, silent=True) or {}
    emp_id = data.get("employee_id")
    name = data.get("name")
    email = data.get("email")
    role = data.get("role", "employee")
    team_id = data.get("team_id", "T01")
    manager_id = data.get("manager_id")
    password = data.get("password", "welcome@2026")

    if not all([emp_id, name, email]):
        return jsonify({"error": "employee_id, name, and email are required"}), 400

    try:
        new_id = create_employee(
            actor=actor,
            employee_id=emp_id.strip(),
            name=name.strip(),
            email=email.strip(),
            role=role.strip(),
            team_id=team_id.strip(),
            manager_id=manager_id.strip() if manager_id else None,
            initial_password=password
        )
        return jsonify({"status": "created", "employee_id": new_id}), 201
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/deactivate-employee", methods=["POST"])
def admin_deactivate_employee():
    actor = _resolve_actor()
    data = request.get_json(force=True, silent=True) or {}
    emp_id = data.get("employee_id")
    if not emp_id:
        return jsonify({"error": "employee_id is required"}), 400
    try:
        deactivate_employee(actor, employee_id=emp_id.strip())
        return jsonify({"status": "deactivated", "employee_id": emp_id}), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/admin/audit-logs", methods=["GET"])
def query_audit_logs():
    actor = _resolve_actor()
    limit = int(request.args.get("limit", 100))
    action_filter = request.args.get("action")
    try:
        logs = get_audit_logs(actor, limit=limit, action_filter=action_filter)
        return jsonify(logs), 200
    except AccessError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
