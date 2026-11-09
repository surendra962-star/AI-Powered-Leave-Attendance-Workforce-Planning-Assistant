from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional, Union, List, Dict

from database.db import DB_PATH, connection, log_audit
from leave_management.service import LeaveError, _as_date


def _is_working_day(conn: sqlite3.Connection, day: date) -> bool:
    if day.weekday() >= 5:
        return False
    return conn.execute(
        "SELECT 1 FROM holidays WHERE date = ? AND holiday_type = 'public'",
        (day.isoformat(),),
    ).fetchone() is None


def _employee_is_on_leave(conn: sqlite3.Connection, employee_id: str, day: date) -> bool:
    return conn.execute(
        """SELECT 1 FROM leave_requests
           WHERE employee_id = ? AND status IN ('approved','pending','needs_review')
             AND start_date <= ? AND end_date >= ? LIMIT 1""",
        (employee_id, day.isoformat(), day.isoformat()),
    ).fetchone() is not None


def team_coverage(team_id: str, day_value: Union[str, date], db_path: Path = DB_PATH,
                  exclude_request_id: Optional[int] = None) -> Dict[str, Any]:
    """Calculate available active team members and coverage for one date."""
    day = _as_date(day_value)
    with connection(db_path) as conn:
        team = conn.execute(
            "SELECT team_id,name,min_coverage_percent FROM teams WHERE team_id = ?",
            (team_id,),
        ).fetchone()
        if team is None:
            raise LeaveError(f"Unknown team: {team_id}")
        employees = conn.execute(
            "SELECT employee_id,name FROM employees WHERE team_id=? AND is_active=1 ORDER BY employee_id",
            (team_id,),
        ).fetchall()
        total = len(employees)
        working = _is_working_day(conn, day)
        absent, available = [], []
        for employee in employees:
            sql = """SELECT request_id FROM leave_requests
                     WHERE employee_id=? AND status IN ('approved','pending','needs_review')
                       AND start_date<=? AND end_date>=?"""
            params: list[Any] = [employee["employee_id"], day.isoformat(), day.isoformat()]
            if exclude_request_id is not None:
                sql += " AND request_id != ?"
                params.append(exclude_request_id)
            sql += " LIMIT 1"
            on_leave = conn.execute(sql, params).fetchone() is not None
            item = {"employee_id": employee["employee_id"], "name": employee["name"]}
            (absent if on_leave else available).append(item)
        available_count = len(available) if working else total
        percent = round(available_count / total * 100, 2) if total else 0.0
        minimum = int(team["min_coverage_percent"])
        return {
            "team_id": team_id, "team_name": team["name"], "date": day.isoformat(),
            "is_working_day": working, "total_active_employees": total,
            "available_count": available_count, "absent_count": len(absent) if working else 0,
            "coverage_percent": percent, "minimum_coverage_percent": minimum,
            "meets_minimum": (not working) or percent >= minimum,
            "available_employees": available if working else [
                {"employee_id": e["employee_id"], "name": e["name"]} for e in employees
            ],
            "planned_absences": absent if working else [],
        }


def assign_backup(deadline_id: int, backup_employee_id: str, assigned_on: Union[str, date],
                  db_path: Path = DB_PATH) -> int:
    """Create/replace a deadline backup after validating team and availability."""
    assigned = _as_date(assigned_on)
    with connection(db_path) as conn:
        deadline = conn.execute(
            "SELECT deadline_id,team_id,owner_id,due_on FROM project_deadlines WHERE deadline_id=?",
            (deadline_id,),
        ).fetchone()
        if deadline is None:
            raise LeaveError(f"Unknown project deadline: {deadline_id}")
        backup = conn.execute(
            "SELECT employee_id,team_id,is_active FROM employees WHERE employee_id=?",
            (backup_employee_id,),
        ).fetchone()
        if backup is None or not backup["is_active"]:
            raise LeaveError("Backup employee does not exist or is inactive.")
        if backup["team_id"] != deadline["team_id"]:
            raise LeaveError("Backup employee must belong to the deadline's team.")
        if backup_employee_id == deadline["owner_id"]:
            raise LeaveError("Project owner cannot be their own backup.")
        due = _as_date(deadline["due_on"])
        if _employee_is_on_leave(conn, backup_employee_id, due):
            raise LeaveError("Backup employee has planned leave on the deadline date.")
        existing = conn.execute(
            "SELECT assignment_id FROM backup_assignments WHERE deadline_id=?", (deadline_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE backup_assignments SET backup_employee_id=?,assigned_on=? WHERE deadline_id=?",
                (backup_employee_id, assigned.isoformat(), deadline_id),
            )
            aid = int(existing["assignment_id"])
        else:
            cursor = conn.execute(
                "INSERT INTO backup_assignments(deadline_id,backup_employee_id,assigned_on) VALUES (?,?,?)",
                (deadline_id, backup_employee_id, assigned.isoformat()),
            )
            aid = int(cursor.lastrowid)
    log_audit("system", "manager", "assign_backup", str(deadline_id), f"Assigned backup {backup_employee_id} to deadline #{deadline_id}", db_path)
    return aid


def evaluate_leave_request(request_id: int, evaluated_on: Optional[Union[str, date]] = None,
                           db_path: Path = DB_PATH, persist: bool = True) -> Dict[str, Any]:
    """Assess coverage/deadline risk; persist evidence without deciding the request."""
    evaluated = _as_date(evaluated_on or date.today())
    with connection(db_path) as conn:
        request = conn.execute(
            """SELECT lr.*,e.team_id,e.name AS employee_name
               FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id
               WHERE lr.request_id=?""", (request_id,),
        ).fetchone()
        if request is None:
            raise LeaveError(f"Unknown leave request: {request_id}")
        if request["status"] not in ("pending", "needs_review"):
            raise LeaveError("Only pending or needs_review requests can be evaluated.")
        start, end = _as_date(request["start_date"]), _as_date(request["end_date"])
        team_id, employee_id = request["team_id"], request["employee_id"]
        minimum = int(conn.execute(
            "SELECT min_coverage_percent FROM teams WHERE team_id=?", (team_id,)
        ).fetchone()[0])

        daily = []
        current = start
        while current <= end:
            if _is_working_day(conn, current):
                coverage = team_coverage(team_id, current, db_path, exclude_request_id=request_id)
                after = max(0, coverage["available_count"] - 1)
                pct = round(after / coverage["total_active_employees"] * 100, 2) if coverage["total_active_employees"] else 0.0
                daily.append({
                    "date": current.isoformat(),
                    "total_active_employees": coverage["total_active_employees"],
                    "available_before_request": coverage["available_count"],
                    "available_after_request": after,
                    "coverage_percent_after_request": pct,
                    "minimum_coverage_percent": minimum,
                    "meets_minimum": pct >= minimum,
                    "planned_absences_before_request": coverage["planned_absences"],
                })
            current += timedelta(days=1)

        deadlines = conn.execute(
            """SELECT pd.deadline_id,pd.title,pd.due_on,pd.critical,pd.owner_id,
                      owner.name AS owner_name,ba.backup_employee_id,backup.name AS backup_name
               FROM project_deadlines pd
               JOIN employees owner ON owner.employee_id=pd.owner_id
               LEFT JOIN backup_assignments ba ON ba.deadline_id=pd.deadline_id
               LEFT JOIN employees backup ON backup.employee_id=ba.backup_employee_id
               WHERE pd.team_id=? AND pd.due_on BETWEEN ? AND ? ORDER BY pd.due_on""",
            (team_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        deadline_evidence = []
        for d in deadlines:
            due = _as_date(d["due_on"])
            requester_owner = d["owner_id"] == employee_id
            backup_id = d["backup_employee_id"]
            backup_available = bool(backup_id) and not _employee_is_on_leave(conn, backup_id, due)
            if d["critical"] and requester_owner and not backup_available:
                risk = "critical_owner_without_available_backup"
            elif d["critical"] and requester_owner:
                risk = "critical_owner_with_available_backup"
            else:
                risk = "deadline_not_owned_by_requester"
            deadline_evidence.append({
                "deadline_id": d["deadline_id"], "title": d["title"], "due_on": d["due_on"],
                "critical": bool(d["critical"]), "owner_id": d["owner_id"],
                "owner_name": d["owner_name"], "requester_is_owner": requester_owner,
                "backup_employee_id": backup_id, "backup_name": d["backup_name"],
                "backup_available_on_due_date": backup_available if backup_id else None,
                "risk": risk,
            })

        breaches = [d for d in daily if not d["meets_minimum"]]
        critical_without_backup = [d for d in deadline_evidence if d["critical"] and d["requester_is_owner"] and not d["backup_available_on_due_date"]]
        critical_with_backup = [d for d in deadline_evidence if d["critical"] and d["requester_is_owner"] and d["backup_available_on_due_date"]]

        # Initialize missing information list early so it can be populated anywhere below
        missing_information = []

        # 1. Advance notice rule check
        submitted_date = _as_date(request["submitted_on"])
        notice_days = (start - submitted_date).days
        if request["leave_type"] == "annual":
            notice_passed = notice_days >= 5
            notice_desc = f"{notice_days} calendar days notice provided (policy requirement: >= 5 days)"
        else:
            notice_passed = True
            notice_desc = f"Advance notice not required for {request['leave_type']} leave"

        # 2. Balance check
        if request["leave_type"] in ("annual", "sick"):
            bal_row = conn.execute(
                "SELECT entitled_days, used_days FROM leave_balances WHERE employee_id=? AND leave_type=? AND year=?",
                (employee_id, request["leave_type"], start.year)
            ).fetchone()
            if bal_row is None:
                # Cannot verify — treat as unknown (pass but flag as missing info)
                balance_passed = True
                bal_desc = f"Balance record unavailable for {request['leave_type']} {start.year} — cannot verify"
                missing_information.append(
                    f"Leave balance record missing for {request['leave_type']} {start.year} — balance cannot be confirmed."
                )
            else:
                entitled = float(bal_row["entitled_days"])
                used = float(bal_row["used_days"])
                rem_days = round(entitled - used, 2)
                balance_passed = rem_days >= float(request["requested_days"])
                bal_desc = f"Remaining balance: {rem_days} days, Requested: {float(request['requested_days'])} days"
        else: # comp_off
            comp_row = conn.execute(
                "SELECT COALESCE(SUM(days), 0.0) FROM comp_off_records WHERE employee_id=? AND status='available' AND expires_on >= ?",
                (employee_id, evaluated.isoformat())
            ).fetchone()
            comp_avail = float(comp_row[0]) if comp_row else 0.0
            balance_passed = comp_avail >= float(request["requested_days"])
            bal_desc = f"Available unexpired comp-off: {comp_avail} days, Requested: {float(request['requested_days'])} days"

        # 3. Contextual attendance information (30-day window)
        window_start = (start - timedelta(days=30)).isoformat()
        att_rows = conn.execute(
            """SELECT status, COUNT(*) as count FROM attendance
               WHERE employee_id = ? AND date BETWEEN ? AND ?
               GROUP BY status""",
            (employee_id, window_start, start.isoformat())
        ).fetchall()
        att_counts = {r["status"]: r["count"] for r in att_rows}
        total_att_days = sum(att_counts.values())
        present_days = att_counts.get("present", 0)
        absent_days = att_counts.get("absent", 0)
        leave_days = att_counts.get("approved_leave", 0)
        att_pct = round(present_days / total_att_days * 100, 1) if total_att_days else 100.0

        attendance_context = {
            "window_start": window_start,
            "window_end": start.isoformat(),
            "total_logged_days": total_att_days,
            "present_days": present_days,
            "absent_days": absent_days,
            "approved_leave_days": leave_days,
            "attendance_rate_percent": att_pct,
            "disclaimer": "Contextual attendance only. Patterns must not be used alone to infer misconduct or make disciplinary decisions."
        }

        # 4. Missing information detection (list initialized earlier; append additional items here)
        if critical_without_backup:
            for c in critical_without_backup:
                missing_information.append(
                    f"Missing backup assignment: Critical project deadline '{c['title']}' (ID #{c['deadline_id']}, due {c['due_on']}) owned by requester has no available backup."
                )
        if not request["reason"] or not request["reason"].strip():
            missing_information.append("Optional leave justification reason was not specified by requester.")
        if total_att_days == 0:
            missing_information.append("No prior attendance logs recorded in the 30-day window preceding this request.")

        # 5. Recommendation labels
        if breaches or critical_without_backup or not notice_passed or not balance_passed:
            recommendation = "high_risk"
            recommendation_label = "Potential policy conflict"
        elif critical_with_backup or deadline_evidence:
            recommendation = "review_required"
            recommendation_label = "Needs manager review"
        else:
            recommendation = "low_risk"
            recommendation_label = "Likely eligible"

        reasons = [
            f"Recommendation: {recommendation_label}."
        ]
        if not notice_passed:
            reasons.append(f"Advance notice policy requirement not satisfied ({notice_desc}).")
        if not balance_passed:
            reasons.append(f"Insufficient leave balance ({bal_desc}).")
        reasons.append(
            "Team coverage falls below the configured minimum on one or more requested working days."
            if breaches else "Team coverage meets the configured minimum on all requested working days."
        )
        if critical_without_backup:
            reasons.append("A critical project deadline owned by the requester has no available backup.")
        elif critical_with_backup:
            reasons.append("A critical project deadline is owned by the requester, but an available backup is assigned.")
        elif deadline_evidence:
            reasons.append("Team project deadlines occur during the requested period; review ownership and delivery impact.")
        else:
            reasons.append("No team project deadlines were found within the requested date range.")

        min_pct = min([d["coverage_percent_after_request"] for d in daily], default=100.0)

        rules_evaluated = [
            {
                "rule": "Advance Notice Period",
                "policy_requirement": ">= 5 calendar days for annual leave",
                "observed": notice_desc,
                "status": "PASS" if notice_passed else "FAIL",
                "detail": f"Submitted on {request['submitted_on']}, requested start date is {request['start_date']}."
            },
            {
                "rule": "Leave Balance Sufficiency",
                "policy_requirement": f"Available {request['leave_type']} balance >= requested working days ({request['requested_days']})",
                "observed": bal_desc,
                "status": "PASS" if balance_passed else "FAIL",
                "detail": "Leave balance is sufficient." if balance_passed else "Insufficient leave balance for requested duration."
            },
            {
                "rule": "Team Minimum Coverage",
                "policy_requirement": f"Team active coverage >= {minimum}% across all requested working days",
                "observed": f"Lowest coverage after request: {min_pct}% ({len(breaches)} breach date(s))",
                "status": "PASS" if len(breaches) == 0 else "FAIL",
                "detail": f"Breach dates: {', '.join(d['date'] for d in breaches)}" if breaches else "All working days meet or exceed team minimum threshold."
            },
            {
                "rule": "Critical Deadline & Backup Protection",
                "policy_requirement": "All critical project deadlines owned by requester must have available backups assigned",
                "observed": f"{len(critical_without_backup)} critical deadline(s) lack available backup",
                "status": "PASS" if len(critical_without_backup) == 0 else "FAIL",
                "detail": "Backup is assigned and available." if not critical_without_backup else "Critical project deadline at risk without assigned backup."
            }
        ]

        evidence = {
            "request_id": request_id, "employee_id": employee_id,
            "employee_name": request["employee_name"], "team_id": team_id,
            "leave_type": request["leave_type"], "start_date": start.isoformat(),
            "end_date": end.isoformat(), "requested_days": float(request["requested_days"]),
            "evaluated_on": evaluated.isoformat(), "team_minimum_coverage_percent": minimum,
            "recommendation_label": recommendation_label,
            "daily_coverage": daily, "project_deadlines": deadline_evidence,
            "coverage_breach_dates": [d["date"] for d in breaches],
            "critical_deadlines_without_available_backup": [d["deadline_id"] for d in critical_without_backup],
            "rules_evaluated": rules_evaluated,
            "missing_information": missing_information,
            "attendance_context": attendance_context,
            "reasons": reasons,
        }
        result = {
            "request_id": request_id,
            "recommendation": recommendation,
            "recommendation_label": recommendation_label,
            "label": recommendation_label,
            "reasons": reasons,
            "rules_evaluated": rules_evaluated,
            "missing_information": missing_information,
            "attendance_context": attendance_context,
            "evidence": evidence,
            "coverage_warning": len(breaches) > 0,
            "coverage_breach_dates": [d["date"] for d in breaches],
            "coverage_percent_after_request": min_pct,
            "coverage_after_percent": min_pct,
            "final_decision": None,
            "automatic_approval": False,
        }
        if persist:
            conn.execute(
                """INSERT INTO decision_history
                   (request_id,recommendation,evidence_json,final_decision,decided_by,decided_on,note)
                   VALUES (?,?,?,NULL,NULL,NULL,?)""",
                (request_id, recommendation, json.dumps(evidence, sort_keys=True),
                 "Deterministic decision support; manager/HR must make the final decision."),
            )
        return result


def list_team_deadlines(team_id: str, start_date: Union[str, date], end_date: Union[str, date],
                        db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """List deadlines and assigned backups for a team within an inclusive date range."""
    start, end = _as_date(start_date), _as_date(end_date)
    if end < start:
        raise LeaveError("End date cannot be before start date.")
    with connection(db_path) as conn:
        if conn.execute("SELECT 1 FROM teams WHERE team_id=?", (team_id,)).fetchone() is None:
            raise LeaveError(f"Unknown team: {team_id}")
        rows = conn.execute(
            """SELECT pd.deadline_id,pd.title,pd.due_on,pd.critical,pd.owner_id,
                      owner.name AS owner_name,ba.backup_employee_id,backup.name AS backup_name
               FROM project_deadlines pd
               JOIN employees owner ON owner.employee_id=pd.owner_id
               LEFT JOIN backup_assignments ba ON ba.deadline_id=pd.deadline_id
               LEFT JOIN employees backup ON backup.employee_id=ba.backup_employee_id
               WHERE pd.team_id=? AND pd.due_on BETWEEN ? AND ? ORDER BY pd.due_on""",
            (team_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]


def recommend_backups(deadline_id: int, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Identify and rank eligible backup candidates for a given deadline.

    Eligibility rules:
    1. Must belong to the same team as the project deadline.
    2. Must be an active employee.
    3. Cannot be the owner of the deadline.
    4. Must not have approved or pending leave on the deadline due date.
    """
    with connection(db_path) as conn:
        deadline = conn.execute(
            "SELECT deadline_id, title, due_on, owner_id, team_id, critical FROM project_deadlines WHERE deadline_id=?",
            (deadline_id,)
        ).fetchone()
        if not deadline:
            raise LeaveError(f"Unknown project deadline: {deadline_id}")
        due = _as_date(deadline["due_on"])
        team_id = deadline["team_id"]
        owner_id = deadline["owner_id"]

        candidates = conn.execute(
            """SELECT employee_id, name, role FROM employees
               WHERE team_id=? AND is_active=1 AND employee_id != ?
               ORDER BY name""",
            (team_id, owner_id)
        ).fetchall()

        recommendations = []
        for cand in candidates:
            cand_id = cand["employee_id"]
            on_leave = _employee_is_on_leave(conn, cand_id, due)
            status = "unavailable_on_leave" if on_leave else "available"
            score = 100 if not on_leave else 0
            reason = (f"{cand['name']} is available on {deadline['due_on']} and belongs to team {team_id}."
                      if not on_leave else
                      f"{cand['name']} has planned leave on {deadline['due_on']}.")
            recommendations.append({
                "employee_id": cand_id,
                "name": cand["name"],
                "role": cand["role"],
                "status": status,
                "score": score,
                "is_eligible": not on_leave,
                "is_available": not on_leave,
                "reason": reason,
            })
        return sorted(recommendations, key=lambda x: (-x["score"], x["name"]))


def team_capacity_forecast(team_id: str, start_date: Union[str, date],
                           end_date: Union[str, date], db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Provide a day-by-day capacity and coverage forecast over an inclusive date range."""
    start, end = _as_date(start_date), _as_date(end_date)
    if end < start:
        raise LeaveError("End date cannot precede start date.")
    current = start
    days = []
    breaches = []
    with connection(db_path) as conn:
        team = conn.execute("SELECT name, min_coverage_percent FROM teams WHERE team_id=?", (team_id,)).fetchone()
        if not team:
            raise LeaveError(f"Unknown team: {team_id}")
        min_pct = int(team["min_coverage_percent"])

    while current <= end:
        cov = team_coverage(team_id, current, db_path=db_path)
        days.append({
            "date": current.isoformat(),
            "weekday": current.strftime("%A"),
            "is_working_day": cov["is_working_day"],
            "total_active": cov["total_active_employees"],
            "available_count": cov["available_count"],
            "absent_count": cov["absent_count"],
            "coverage_percent": cov["coverage_percent"],
            "meets_minimum": cov["meets_minimum"],
            "planned_absences": cov["planned_absences"],
        })
        if not cov["meets_minimum"]:
            breaches.append(current.isoformat())
        current += timedelta(days=1)

    return {
        "team_id": team_id,
        "team_name": team["name"],
        "minimum_coverage_percent": min_pct,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_days_evaluated": len(days),
        "coverage_breach_count": len(breaches),
        "breach_dates": breaches,
        "forecast": days,
    }




def get_decision_history(request_id: int, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve the chronological audit history of AI evaluations and human decisions for a leave request."""
    from dashboards.service import get_decision_history as _gdh
    return _gdh(request_id, db_path=db_path)


