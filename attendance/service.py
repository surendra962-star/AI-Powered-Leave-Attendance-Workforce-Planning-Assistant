"""Attendance management service.

Handles:
- Daily attendance recording (present, absent, approved_leave)
- Check-in and check-out timestamps
- Employee personal attendance history
- Manager team attendance tracking
- HR organization-wide attendance overview
- Monthly summaries and attendance percentage calculations
- CSV export for reporting

Attendance percentage formula:
  attendance_percent = (present_days / (present_days + absent_days)) * 100
Approved leave days are excluded from the denominator.
Missing records are treated as unrecorded (not automatically counted as absent).
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

from database.db import DB_PATH, connection, log_audit
from access_control.service import UserContext, require_role, require_employee_scope

VALID_STATUSES = {"present", "absent", "approved_leave"}


class AttendanceError(ValueError):
    """Raised when attendance operations violate business rules."""
    pass


def _as_date(value: Union[str, date]) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def record_attendance(actor: UserContext, employee_id: str, attendance_date: Union[str, date],
                      status: str, check_in: Optional[str] = None, check_out: Optional[str] = None,
                      db_path: Path = DB_PATH) -> int:
    """Record or update attendance for an employee.

    RBAC:
    - Employee can record for self (e.g. daily self check-in).
    - Manager can record for members of their team.
    - HR can record for any employee.
    """
    require_employee_scope(actor, employee_id, db_path)
    att_date = _as_date(attendance_date).isoformat()
    clean_status = status.strip().lower()
    if clean_status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of: {sorted(VALID_STATUSES)}")

    with connection(db_path) as conn:
        emp = conn.execute("SELECT employee_id, name, is_active FROM employees WHERE employee_id=?",
                           (employee_id,)).fetchone()
        if not emp or not emp["is_active"]:
            raise ValueError(f"Employee {employee_id} does not exist or is inactive.")

        cursor = conn.execute(
            """INSERT INTO attendance (employee_id, date, status, check_in, check_out)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(employee_id, date) DO UPDATE SET
                   status=excluded.status,
                   check_in=COALESCE(excluded.check_in, attendance.check_in),
                   check_out=COALESCE(excluded.check_out, attendance.check_out)""",
            (employee_id, att_date, clean_status, check_in, check_out)
        )
        rowid = int(cursor.lastrowid or 0)

    log_audit(actor.employee_id, actor.role, "record_attendance", employee_id,
              f"Recorded status '{clean_status}' for {att_date}", db_path)
    return rowid


def clock_in(actor: UserContext, employee_id: Optional[str] = None,
             att_date: Optional[Union[str, date]] = None,
             time_str: Optional[str] = None,
             db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Record clock-in timestamp for today. Prevents duplicate clock-ins."""
    target_emp = employee_id or actor.employee_id
    require_employee_scope(actor, target_emp, db_path)
    today = _as_date(att_date or date.today()).isoformat()
    now_time = time_str or datetime.now().strftime("%H:%M:%S")

    with connection(db_path) as conn:
        existing = conn.execute(
            "SELECT attendance_id, check_in, check_out, status FROM attendance WHERE employee_id=? AND date=?",
            (target_emp, today)
        ).fetchone()
        if existing and existing["check_in"]:
            raise AttendanceError(
                f"Duplicate clock-in prevented: Employee {target_emp} has already clocked in on {today} at {existing['check_in']}."
            )

    record_attendance(actor, target_emp, today, "present", check_in=now_time, db_path=db_path)
    return {
        "employee_id": target_emp,
        "date": today,
        "check_in": now_time,
        "status": "present",
        "message": f"Clocked in at {now_time}"
    }


def clock_out(actor: UserContext, employee_id: Optional[str] = None,
              att_date: Optional[Union[str, date]] = None,
              time_str: Optional[str] = None,
              allow_missing_check_in: bool = False,
              db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Record clock-out timestamp for today. Verifies prior clock-in unless explicitly bypassed."""
    target_emp = employee_id or actor.employee_id
    require_employee_scope(actor, target_emp, db_path)
    today = _as_date(att_date or date.today()).isoformat()
    now_time = time_str or datetime.now().strftime("%H:%M:%S")

    with connection(db_path) as conn:
        existing = conn.execute(
            "SELECT check_in, status FROM attendance WHERE employee_id=? AND date=?",
            (target_emp, today)
        ).fetchone()

    if (not existing or not existing["check_in"]) and not allow_missing_check_in:
        raise AttendanceError(
            f"Cannot clock out: No prior clock-in record found for {target_emp} on {today}."
        )

    status = existing["status"] if existing else "present"
    record_attendance(actor, target_emp, today, status, check_out=now_time, db_path=db_path)
    return {
        "employee_id": target_emp,
        "date": today,
        "check_in": existing["check_in"] if existing else None,
        "check_out": now_time,
        "status": status,
        "message": f"Clocked out at {now_time}"
    }


def get_employee_attendance(actor: UserContext, employee_id: Optional[str] = None,
                            start_date: Optional[Union[str, date]] = None,
                            end_date: Optional[Union[str, date]] = None,
                            db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve personal attendance history with scope enforcement."""
    target_emp = employee_id or actor.employee_id
    require_employee_scope(actor, target_emp, db_path)

    query = """SELECT attendance_id, employee_id, date, status, check_in, check_out
               FROM attendance WHERE employee_id=?"""
    params: List[Any] = [target_emp]

    if start_date:
        query += " AND date >= ?"
        params.append(_as_date(start_date).isoformat())
    if end_date:
        query += " AND date <= ?"
        params.append(_as_date(end_date).isoformat())

    query += " ORDER BY date DESC"

    with connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_team_attendance(actor: UserContext, target_date: Optional[Union[str, date]] = None,
                         team_id: Optional[str] = None,
                         date_str: Optional[Union[str, date]] = None,
                         db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Manager/HR team attendance review for a given date."""
    require_role(actor, "manager", "hr")
    # Flexible argument parsing: if target_date is a team ID (e.g. starts with 'T')
    if isinstance(target_date, str) and (target_date.startswith("T") or len(target_date) < 5) and team_id is None:
        t_id = target_date
        actual_date = date_str or date.today()
    else:
        t_id = actor.team_id if actor.role == "manager" else (team_id or actor.team_id)
        actual_date = date_str or target_date or date.today()
    the_date = _as_date(actual_date).isoformat()

    with connection(db_path) as conn:
        rows = conn.execute(
            """SELECT e.employee_id, e.name, e.team_id,
                      COALESCE(a.status, 'unrecorded') as status,
                      a.check_in, a.check_out, a.date
               FROM employees e
               LEFT JOIN attendance a ON a.employee_id=e.employee_id AND a.date=?
               WHERE e.team_id=? AND e.is_active=1
               ORDER BY e.name""",
            (the_date, t_id)
        ).fetchall()
        return [dict(r) for r in rows]


def get_hr_attendance_overview(actor: UserContext, target_date: Optional[Union[str, date]] = None,
                               date_str: Optional[Union[str, date]] = None,
                               db_path: Path = DB_PATH) -> Dict[str, Any]:
    """HR organization-wide daily attendance summary."""
    require_role(actor, "hr")
    actual_date = date_str or target_date or date.today()
    the_date = _as_date(actual_date).isoformat()

    with connection(db_path) as conn:
        total_active = conn.execute("SELECT COUNT(*) FROM employees WHERE is_active=1").fetchone()[0]
        rows = conn.execute(
            """SELECT e.employee_id, e.name, e.team_id, t.name as team_name,
                      COALESCE(a.status, 'unrecorded') as status,
                      a.check_in, a.check_out
               FROM employees e
               JOIN teams t ON t.team_id = e.team_id
               LEFT JOIN attendance a ON a.employee_id=e.employee_id AND a.date=?
               WHERE e.is_active=1
               ORDER BY e.team_id, e.name""",
            (the_date,)
        ).fetchall()

        records = [dict(r) for r in rows]
        present = sum(1 for r in records if r["status"] == "present")
        absent = sum(1 for r in records if r["status"] == "absent")
        approved_leave = sum(1 for r in records if r["status"] == "approved_leave")
        unrecorded = sum(1 for r in records if r["status"] == "unrecorded")

    return {
        "date": the_date,
        "total_active_employees": int(total_active),
        "present_count": present,
        "absent_count": absent,
        "approved_leave_count": approved_leave,
        "unrecorded_count": unrecorded,
        "records": records,
    }


def get_missing_clock_outs(actor: UserContext, before_date: Optional[Union[str, date]] = None,
                           employee_id: Optional[str] = None,
                           team_id: Optional[str] = None,
                           db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Identify attendance records where an employee clocked in but never recorded clock-out."""
    cutoff = _as_date(before_date or date.today()).isoformat()
    where = ["a.status = 'present'", "a.check_in IS NOT NULL", "(a.check_out IS NULL OR a.check_out = '')", "a.date <= ?"]
    params: List[Any] = [cutoff]

    if actor.role == "employee":
        where.append("a.employee_id = ?")
        params.append(actor.employee_id)
    elif actor.role == "manager":
        where.append("e.team_id = ?")
        params.append(actor.team_id)
        if employee_id:
            where.append("a.employee_id = ?")
            params.append(employee_id)
    else: # hr
        if team_id:
            where.append("e.team_id = ?")
            params.append(team_id)
        if employee_id:
            where.append("a.employee_id = ?")
            params.append(employee_id)

    with connection(db_path) as conn:
        rows = conn.execute(
            f"""SELECT a.attendance_id, a.employee_id, e.name, e.team_id, a.date, a.status, a.check_in, a.check_out
                FROM attendance a
                JOIN employees e ON e.employee_id = a.employee_id
                WHERE {' AND '.join(where)}
                ORDER BY a.date DESC, a.employee_id""",
            params
        ).fetchall()
        return [dict(r) for r in rows]


def regularize_missing_clock_out(actor: UserContext, employee_id: str,
                                attendance_date: Union[str, date],
                                default_check_out: str = "17:00:00",
                                note: str = "Auto-regularized missing clock-out",
                                db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Resolve a missing clock-out by recording an authorized default check-out timestamp."""
    require_role(actor, "manager", "hr")
    att_date = _as_date(attendance_date).isoformat()
    with connection(db_path) as conn:
        rec = conn.execute(
            "SELECT attendance_id, check_in, check_out, status FROM attendance WHERE employee_id=? AND date=?",
            (employee_id, att_date)
        ).fetchone()
        if not rec:
            raise AttendanceError(f"No attendance record exists for {employee_id} on {att_date}.")
        if rec["check_out"]:
            raise AttendanceError(f"Clock-out is already recorded for {employee_id} on {att_date} ({rec['check_out']}).")

        conn.execute(
            "UPDATE attendance SET check_out=? WHERE employee_id=? AND date=?",
            (default_check_out, employee_id, att_date)
        )

    log_audit(actor.employee_id, actor.role, "regularize_missing_clock_out", employee_id,
              f"Set check_out={default_check_out} for {att_date}. Note: {note}", db_path)
    return {
        "employee_id": employee_id,
        "date": att_date,
        "check_in": rec["check_in"],
        "check_out": default_check_out,
        "status": rec["status"],
        "regularized_by": actor.employee_id,
        "note": note
    }


def get_monthly_attendance_summary(actor: UserContext, month: str,
                                   employee_id: Optional[str] = None,
                                   team_id: Optional[str] = None,
                                   db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Calculate monthly attendance statistics and percentages.

    Formula:
      attendance_percentage = (present_days / (present_days + absent_days)) * 100
      (Approved leaves are excluded from denominator so scheduled time is accurate).
    """
    first_day = date.fromisoformat(month + "-01")
    # compute end of month
    import calendar
    _, last_day_num = calendar.monthrange(first_day.year, first_day.month)
    last_day = date(first_day.year, first_day.month, last_day_num)

    target_emp = employee_id
    target_team = team_id

    if actor.role == "employee":
        target_emp = actor.employee_id
        target_team = actor.team_id
    elif actor.role == "manager":
        require_role(actor, "manager")
        target_team = actor.team_id

    with connection(db_path) as conn:
        where = ["substr(a.date, 1, 7) = ?"]
        params: List[Any] = [month]

        if target_emp:
            where.append("a.employee_id = ?")
            params.append(target_emp)
        if target_team:
            where.append("e.team_id = ?")
            params.append(target_team)

        sql = f"""SELECT COUNT(*) as total_recorded,
                         SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present_days,
                         SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) as absent_days,
                         SUM(CASE WHEN a.status='approved_leave' THEN 1 ELSE 0 END) as approved_leave_days,
                         SUM(CASE WHEN a.status='present' AND a.check_in IS NOT NULL AND (a.check_out IS NULL OR a.check_out='') THEN 1 ELSE 0 END) as missing_clock_outs
                  FROM attendance a
                  JOIN employees e ON e.employee_id=a.employee_id
                  WHERE {' AND '.join(where)}"""
        row = conn.execute(sql, params).fetchone()

        # Count calendar working days (Mon-Fri) excluding public holidays
        pub_holidays = {
            r["date"] for r in conn.execute(
                "SELECT date FROM holidays WHERE holiday_type='public' AND date BETWEEN ? AND ?",
                (first_day.isoformat(), last_day.isoformat())
            ).fetchall()
        }

    calendar_working_days = 0
    cur = first_day
    while cur <= last_day:
        if cur.weekday() < 5 and cur.isoformat() not in pub_holidays:
            calendar_working_days += 1
        cur += timedelta(days=1)

    present = int(row["present_days"] or 0)
    absent = int(row["absent_days"] or 0)
    approved_leave = int(row["approved_leave_days"] or 0)
    missing_clock_outs = int(row["missing_clock_outs"] or 0)
    total = int(row["total_recorded"] or 0)
    denom = present + absent
    pct = round((present / denom) * 100.0, 2) if denom > 0 else None
    unrecorded = max(0, calendar_working_days - (present + absent + approved_leave))

    return {
        "month": month,
        "employee_id": target_emp,
        "team_id": target_team,
        "total_recorded_days": total,
        "working_days_in_month": calendar_working_days,
        "present_days": present,
        "absent_days": absent,
        "approved_leave_days": approved_leave,
        "missing_clock_outs": missing_clock_outs,
        "unrecorded_days": unrecorded,
        "present": present,
        "absent": absent,
        "approved_leave": approved_leave,
        "attendance_percentage": pct,
        "calculation_note": "Formula: Present / (Present + Absent) * 100. Approved leave excluded from denominator."
    }


def export_attendance_csv(actor: UserContext, start_date: Optional[Union[str, date]] = None,
                          end_date: Optional[Union[str, date]] = None,
                          employee_id: Optional[str] = None, team_id: Optional[str] = None,
                          db_path: Path = DB_PATH) -> str:
    """Generate a CSV string of attendance records within the given date range."""
    s_date = _as_date(start_date or "2020-01-01").isoformat()
    e_date = _as_date(end_date or "2030-12-31").isoformat()

    query = """SELECT a.attendance_id, a.date, a.employee_id, e.name, e.team_id, t.name as team_name,
                      a.status, a.check_in, a.check_out
               FROM attendance a
               JOIN employees e ON e.employee_id=a.employee_id
               JOIN teams t ON t.team_id=e.team_id
               WHERE a.date BETWEEN ? AND ?"""
    params: List[Any] = [s_date, e_date]

    if actor.role == "employee":
        query += " AND a.employee_id = ?"
        params.append(actor.employee_id)
    elif actor.role == "manager":
        query += " AND e.team_id = ?"
        params.append(actor.team_id)
        if employee_id:
            query += " AND a.employee_id = ?"
            params.append(employee_id)
    else:
        if team_id:
            query += " AND e.team_id = ?"
            params.append(team_id)
        if employee_id:
            query += " AND a.employee_id = ?"
            params.append(employee_id)

    query += " ORDER BY a.date DESC, e.team_id, e.name"

    with connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ATTENDANCE REPORT", f"From: {s_date}", f"To: {e_date}"])
    writer.writerow([])
    writer.writerow(["Attendance ID", "Date", "Employee ID", "Name", "Team ID", "Team Name", "Status", "Check In", "Check Out"])
    for r in rows:
        writer.writerow([r["attendance_id"], r["date"], r["employee_id"], r["name"], r["team_id"], r["team_name"], r["status"], r["check_in"] or "", r["check_out"] or ""])

    return output.getvalue()
