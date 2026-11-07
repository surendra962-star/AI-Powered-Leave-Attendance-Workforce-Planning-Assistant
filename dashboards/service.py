"""Read-only employee, manager and HR dashboards with enforced data scope."""
from __future__ import annotations
import json
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
from database.db import DB_PATH, connection
from access_control.service import UserContext, AccessError, require_role


def employee_dashboard(actor: UserContext, db_path=DB_PATH) -> Dict[str, Any]:
    """Return only the signed-in employee's balances, leave, comp-off and attendance."""
    today_str = date.today().isoformat()
    with connection(db_path) as conn:
        balances = []
        for r in conn.execute(
            """SELECT leave_type, year, entitled_days, used_days
               FROM leave_balances WHERE employee_id=? ORDER BY year, leave_type""",
            (actor.employee_id,)
        ):
            ent = float(r["entitled_days"])
            used = float(r["used_days"])
            rem = round(ent - used, 2)
            pending_row = conn.execute(
                """SELECT COALESCE(SUM(requested_days), 0.0) as pending_days
                   FROM leave_requests
                   WHERE employee_id=? AND leave_type=? AND status IN ('pending', 'needs_review')
                   AND strftime('%Y', start_date)=?""",
                (actor.employee_id, r["leave_type"], str(r["year"]))
            ).fetchone()
            pend = float(pending_row["pending_days"]) if pending_row else 0.0
            avail = round(max(0.0, rem - pend), 2)
            balances.append({
                "leave_type": r["leave_type"],
                "year": r["year"],
                "entitled_days": ent,
                "used_days": used,
                "pending_days": pend,
                "remaining_days": rem,
                "available_days": avail,
            })
        requests = [dict(r) for r in conn.execute("""SELECT request_id,leave_type,start_date,end_date,
            requested_days,status,submitted_on,approval_due_on FROM leave_requests WHERE employee_id=?
            ORDER BY submitted_on DESC,request_id DESC""", (actor.employee_id,))]

        # Detailed attendance breakdown
        att_row = conn.execute("""SELECT COUNT(*) AS total,
            SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) AS present,
            SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) AS absent,
            SUM(CASE WHEN status='approved_leave' THEN 1 ELSE 0 END) AS approved_leave,
            SUM(CASE WHEN status IN ('absent','approved_leave') THEN 1 ELSE 0 END) AS not_present
            FROM attendance WHERE employee_id=?""", (actor.employee_id,)).fetchone()
        present = int(att_row["present"] or 0)
        absent = int(att_row["absent"] or 0)
        total = int(att_row["total"] or 0)
        approved_leave = int(att_row["approved_leave"] or 0)
        not_present = int(att_row["not_present"] or 0)
        att_pct = round(present / (present + absent) * 100, 2) if (present + absent) else None

        # Comp-off balance summary
        comp_off_row = conn.execute("""
            SELECT
                COALESCE(SUM(days), 0.0) as total_earned,
                COALESCE(SUM(CASE WHEN status='available' AND expires_on >= ? THEN days ELSE 0.0 END), 0.0) as available,
                COALESCE(SUM(CASE WHEN status='used' THEN days ELSE 0.0 END), 0.0) as used,
                COALESCE(SUM(CASE WHEN status='expired' OR (status='available' AND expires_on < ?) THEN days ELSE 0.0 END), 0.0) as expired
            FROM comp_off_records WHERE employee_id=?
        """, (today_str, today_str, actor.employee_id)).fetchone()
        comp_summary = {
            "total_earned": float(comp_off_row["total_earned"] or 0.0),
            "available_days": float(comp_off_row["available"] or 0.0),
            "used_days": float(comp_off_row["used"] or 0.0),
            "expired_days": float(comp_off_row["expired"] or 0.0)
        }

        # Upcoming holidays in next 30 days
        h_end = (date.today() + timedelta(days=30)).isoformat()
        upcoming_holidays = [dict(r) for r in conn.execute(
            "SELECT date, name, holiday_type FROM holidays WHERE date BETWEEN ? AND ? ORDER BY date",
            (today_str, h_end)
        ).fetchall()]

    return {
        "employee": {
            "employee_id": actor.employee_id,
            "name": actor.name,
            "team_id": actor.team_id,
            "role": actor.role
        },
        "balances": balances,
        "comp_off": comp_summary,
        "comp_off_summary": comp_summary,
        "leave_requests": requests,
        "attendance": {
            "total": total,
            "present": present,
            "absent": absent,
            "approved_leave": approved_leave,
            "not_present": not_present,
            "attendance_percent": att_pct,
            "attendance_percentage": att_pct
        },
        "upcoming_holidays": upcoming_holidays
    }


def manager_dashboard(actor: UserContext, db_path=DB_PATH, team_id: Optional[str] = None) -> Dict[str, Any]:
    """Return team-level pending requests, coverage snapshot, deadlines, and comp-off balances."""
    require_role(actor, "manager", "hr")
    if isinstance(db_path, str) and not ("/" in db_path or db_path.endswith(".db") or "\\" in db_path) and team_id is None:
        actual_team_id = db_path
        actual_db_path = DB_PATH
    else:
        actual_team_id = team_id
        actual_db_path = db_path

    if actor.role == "manager":
        if actual_team_id not in (None, actor.team_id):
            raise AccessError("Managers may only access their assigned team's dashboard.")
        t_id = actor.team_id
    else:
        t_id = actual_team_id or actor.team_id or "T01"

    today = date.today()
    today_str = today.isoformat()
    horizon_30 = (today + timedelta(days=30)).isoformat()

    with connection(actual_db_path) as conn:
        team = conn.execute("SELECT name,min_coverage_percent FROM teams WHERE team_id=?", (t_id,)).fetchone()
        if team is None:
            raise AccessError("Manager team does not exist.")
        min_cov = int(team["min_coverage_percent"])

        # Pending leave requests with approval deadline status
        pending_raw = conn.execute("""SELECT lr.request_id,lr.employee_id,e.name AS employee_name,
            lr.leave_type,lr.start_date,lr.end_date,lr.requested_days,lr.status,lr.submitted_on,
            lr.approval_due_on
            FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id
            WHERE e.team_id=? AND e.is_active=1 AND lr.status IN ('pending','needs_review')
            ORDER BY lr.start_date,lr.request_id""", (t_id,)).fetchall()

        pending = []
        pending_deadlines = []
        for r in pending_raw:
            d = dict(r)
            appr_due = d.get("approval_due_on")
            is_overdue = False
            days_due = None
            if appr_due:
                try:
                    due_d = date.fromisoformat(appr_due)
                    is_overdue = due_d < today
                    days_due = (due_d - today).days
                except Exception:
                    pass
            d["is_overdue"] = is_overdue
            d["days_until_approval_due"] = days_due
            pending.append(d)
            if appr_due:
                pending_deadlines.append({
                    "request_id": d["request_id"],
                    "employee_id": d["employee_id"],
                    "employee_name": d["employee_name"],
                    "approval_due_on": appr_due,
                    "is_overdue": is_overdue,
                    "days_until_due": days_due,
                    "start_date": d["start_date"],
                    "requested_days": d["requested_days"],
                })
        pending_deadlines.sort(key=lambda x: (not x["is_overdue"], x["approval_due_on"]))

        deadlines = [dict(r) for r in conn.execute("""SELECT d.deadline_id,d.title,d.due_on,d.critical,
            d.owner_id,e.name AS owner_name,b.backup_employee_id,be.name AS backup_name
            FROM project_deadlines d JOIN employees e ON e.employee_id=d.owner_id
            LEFT JOIN backup_assignments b ON b.deadline_id=d.deadline_id
            LEFT JOIN employees be ON be.employee_id=b.backup_employee_id
            WHERE d.team_id=? ORDER BY d.due_on""", (t_id,))]

        headcount = conn.execute("SELECT COUNT(*) FROM employees WHERE team_id=? AND is_active=1", (t_id,)).fetchone()[0]
        counts = {r["status"]: r["n"] for r in conn.execute("""SELECT lr.status,COUNT(*) AS n
            FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id
            WHERE e.team_id=? GROUP BY lr.status""", (t_id,))}

        # Leave type breakdown for team
        leave_type_breakdown = {}
        for r in conn.execute("""
            SELECT lr.leave_type, COUNT(*) as request_count, SUM(lr.requested_days) as total_days
            FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id
            WHERE e.team_id=? GROUP BY lr.leave_type
        """, (t_id,)).fetchall():
            leave_type_breakdown[r["leave_type"]] = {
                "request_count": int(r["request_count"]),
                "total_days": float(r["total_days"] or 0.0)
            }

        # Team member comp-off balances
        team_comp_off = [dict(r) for r in conn.execute("""
            SELECT e.employee_id, e.name,
                   COALESCE(SUM(c.days), 0.0) as total_earned,
                   COALESCE(SUM(CASE WHEN c.status='available' AND c.expires_on >= ? THEN c.days ELSE 0 END), 0.0) as available_days,
                   COALESCE(SUM(CASE WHEN c.status='used' THEN c.days ELSE 0 END), 0.0) as used_days,
                   COALESCE(SUM(CASE WHEN c.status='expired' OR (c.status='available' AND c.expires_on < ?) THEN c.days ELSE 0 END), 0.0) as expired_days
            FROM employees e
            LEFT JOIN comp_off_records c ON c.employee_id = e.employee_id
            WHERE e.team_id = ? AND e.is_active = 1
            GROUP BY e.employee_id, e.name
            ORDER BY e.name
        """, (today_str, today_str, t_id)).fetchall()]

        # Upcoming comp-off expiries for team (next 30 days)
        upcoming_compoff_expiries = [dict(r) for r in conn.execute("""
            SELECT c.comp_off_id, c.employee_id, e.name as employee_name, c.days, c.expires_on, c.work_reference
            FROM comp_off_records c JOIN employees e ON e.employee_id = c.employee_id
            WHERE e.team_id = ? AND c.status = 'available' AND c.expires_on BETWEEN ? AND ?
            ORDER BY c.expires_on
        """, (t_id, today_str, horizon_30)).fetchall()]

        # Upcoming holidays (next 30 days)
        upcoming_holidays = [dict(r) for r in conn.execute(
            "SELECT date, name, holiday_type FROM holidays WHERE date BETWEEN ? AND ? ORDER BY date",
            (today_str, horizon_30)
        ).fetchall()]

        # Upcoming project deadlines (next 30 days)
        upcoming_deadlines = [d for d in deadlines if today_str <= d["due_on"] <= horizon_30]

    # Calculate low-coverage warnings for the upcoming 30 days
    from workforce_planning.service import team_coverage
    low_coverage_warnings = []
    cur_d = today
    for _ in range(30):
        cov = team_coverage(t_id, cur_d, db_path=actual_db_path)
        if cov["is_working_day"] and not cov["meets_minimum"]:
            low_coverage_warnings.append({
                "date": cur_d.isoformat(),
                "coverage_percent": cov["coverage_percent"],
                "minimum_coverage_percent": min_cov,
                "available_count": cov["available_count"],
                "total_active_employees": cov["total_active_employees"],
                "planned_absences": cov["planned_absences"]
            })
        cur_d += timedelta(days=1)

    return {
        "team": {
            "team_id": t_id,
            "name": team["name"],
            "minimum_coverage_percent": min_cov,
            "active_headcount": int(headcount)
        },
        "leave_counts": counts,
        "leave_type_breakdown": leave_type_breakdown,
        "pending_requests": pending,
        "pending_approval_deadlines": pending_deadlines,
        "comp_off_balances": team_comp_off,
        "deadlines": deadlines,
        "upcoming_deadlines": upcoming_deadlines,
        "upcoming_compoff_expiries": upcoming_compoff_expiries,
        "upcoming_holidays": upcoming_holidays,
        "low_coverage_warnings": low_coverage_warnings
    }


def hr_dashboard(actor: UserContext, db_path=DB_PATH) -> dict:
    """Return organization-wide aggregate metrics, comp-off liabilities, and request queue; HR only."""
    require_role(actor, "hr")
    today = date.today()
    today_str = today.isoformat()
    horizon_30 = (today + timedelta(days=30)).isoformat()

    with connection(db_path) as conn:
        headcount = conn.execute("SELECT COUNT(*) FROM employees WHERE is_active=1").fetchone()[0]
        by_team = [dict(r) for r in conn.execute("""SELECT t.team_id,t.name,COUNT(e.employee_id) AS active_headcount
            FROM teams t LEFT JOIN employees e ON e.team_id=t.team_id AND e.is_active=1
            GROUP BY t.team_id,t.name ORDER BY t.team_id""")]
        statuses = {r["status"]: r["n"] for r in conn.execute("SELECT status,COUNT(*) AS n FROM leave_requests GROUP BY status")}

        # Org-wide leave-type breakdown
        leave_type_breakdown = {}
        for r in conn.execute("""
            SELECT leave_type, COUNT(*) as request_count, SUM(requested_days) as total_days
            FROM leave_requests GROUP BY leave_type
        """).fetchall():
            leave_type_breakdown[r["leave_type"]] = {
                "request_count": int(r["request_count"]),
                "total_days": float(r["total_days"] or 0.0)
            }

        queue_raw = conn.execute("""SELECT lr.request_id,lr.employee_id,e.name AS employee_name,
            t.name AS team_name,e.team_id,lr.leave_type,lr.start_date,lr.end_date,lr.requested_days,
            lr.status,lr.approval_due_on
            FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id
            JOIN teams t ON t.team_id=e.team_id WHERE lr.status IN ('pending','needs_review')
            ORDER BY lr.start_date,lr.request_id""").fetchall()

        queue = []
        for r in queue_raw:
            d = dict(r)
            appr_due = d.get("approval_due_on")
            is_overdue = False
            days_due = None
            if appr_due:
                try:
                    due_d = date.fromisoformat(appr_due)
                    is_overdue = due_d < today
                    days_due = (due_d - today).days
                except Exception:
                    pass
            d["is_overdue"] = is_overdue
            d["days_until_approval_due"] = days_due
            queue.append(d)

        policies = [dict(r) for r in conn.execute("""SELECT policy_id,title,version,effective_from,effective_to,is_active
            FROM policy_documents ORDER BY title,version""")]

        # Org-wide comp-off totals
        comp_off_row = conn.execute("""
            SELECT
                COALESCE(SUM(days), 0.0) as total_earned,
                COALESCE(SUM(CASE WHEN status='available' AND expires_on >= ? THEN days ELSE 0.0 END), 0.0) as available,
                COALESCE(SUM(CASE WHEN status='used' THEN days ELSE 0.0 END), 0.0) as used,
                COALESCE(SUM(CASE WHEN status='expired' OR (status='available' AND expires_on < ?) THEN days ELSE 0.0 END), 0.0) as expired
            FROM comp_off_records
        """, (today_str, today_str)).fetchone()
        comp_summary = {
            "total_earned": float(comp_off_row["total_earned"] or 0.0),
            "available_days": float(comp_off_row["available"] or 0.0),
            "used_days": float(comp_off_row["used"] or 0.0),
            "expired_days": float(comp_off_row["expired"] or 0.0)
        }

        upcoming_holidays = [dict(r) for r in conn.execute(
            "SELECT date, name, holiday_type FROM holidays WHERE date BETWEEN ? AND ? ORDER BY date",
            (today_str, horizon_30)
        ).fetchall()]

        critical_deadlines = [dict(r) for r in conn.execute("""
            SELECT d.deadline_id, d.title, d.due_on, d.team_id, t.name as team_name, d.owner_id, e.name as owner_name
            FROM project_deadlines d
            JOIN teams t ON t.team_id = d.team_id
            JOIN employees e ON e.employee_id = d.owner_id
            WHERE d.critical = 1 AND d.due_on BETWEEN ? AND ?
            ORDER BY d.due_on
        """, (today_str, horizon_30)).fetchall()]

    return {
        "active_headcount": int(headcount),
        "teams": by_team,
        "leave_status_counts": statuses,
        "leave_type_breakdown": leave_type_breakdown,
        "pending_queue": queue,
        "policies": policies,
        "comp_off_summary": comp_summary,
        "upcoming_holidays": upcoming_holidays,
        "upcoming_critical_deadlines": critical_deadlines
    }


def list_employee_leave(actor: UserContext, employee_id: str, db_path=DB_PATH) -> list[dict]:
    """Example protected detail endpoint: self, same-team manager, or HR."""
    from access_control.service import require_employee_scope
    require_employee_scope(actor, employee_id, db_path)
    with connection(db_path) as conn:
        return [dict(r) for r in conn.execute("""SELECT request_id,leave_type,start_date,end_date,
            requested_days,status FROM leave_requests WHERE employee_id=? ORDER BY start_date""", (employee_id,))]


def get_decision_history(request_id: int, db_path=DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve the chronological audit history of AI evaluations and human decisions for a leave request."""
    with connection(db_path) as conn:
        rows = conn.execute("""
            SELECT dh.decision_id, dh.request_id, dh.recommendation, dh.evidence_json,
                   dh.final_decision, dh.decided_by, e.name AS decided_by_name,
                   dh.decided_on, dh.note
            FROM decision_history dh
            LEFT JOIN employees e ON e.employee_id = dh.decided_by
            WHERE dh.request_id = ?
            ORDER BY dh.decision_id ASC
        """, (request_id,)).fetchall()
        history = []
        for r in rows:
            ev = {}
            if r["evidence_json"]:
                try:
                    ev = json.loads(r["evidence_json"])
                except Exception:
                    pass
            history.append({
                "decision_id": r["decision_id"],
                "request_id": r["request_id"],
                "recommendation": r["recommendation"],
                "evidence": ev,
                "final_decision": r["final_decision"],
                "decided_by": r["decided_by"],
                "decided_by_name": r["decided_by_name"],
                "decided_on": r["decided_on"],
                "note": r["note"],
                "is_ai_recommendation": r["final_decision"] is None,
                "is_human_decision": r["final_decision"] is not None
            })
        return history

