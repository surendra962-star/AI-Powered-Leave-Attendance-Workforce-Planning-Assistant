from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional, Union, List, Dict, Any

from database.db import DB_PATH, connection, log_audit
from access_control.service import UserContext, require_role, require_employee_scope, AccessError

LeaveType = Literal["annual", "sick", "comp_off"]


class LeaveError(AccessError, ValueError):
    """Raised when a leave operation violates a business or access rule."""


def _as_date(value: Union[str, date]) -> date:
    if isinstance(value, datetime):
        raise LeaveError("Use a date, not a datetime.")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise LeaveError(f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


def working_days(start: Union[str, date], end: Union[str, date],
                 db_path: Path = DB_PATH,
                 exclude_optional_holidays: bool = False) -> int:
    """Count Monday-Friday dates, excluding designated public holidays.

    Optional holidays remain working days unless explicitly excluded by setting
    exclude_optional_holidays=True (when employee elects to claim an optional holiday).
    """
    first, last = _as_date(start), _as_date(end)
    if last < first:
        raise LeaveError("End date cannot be before start date.")
    with connection(db_path) as conn:
        holiday_types = ("public", "optional") if exclude_optional_holidays else ("public",)
        placeholders = ",".join("?" for _ in holiday_types)
        holidays = {
            row["date"] for row in conn.execute(
                f"SELECT date FROM holidays WHERE holiday_type IN ({placeholders}) "
                f"AND date BETWEEN ? AND ?", (*holiday_types, first.isoformat(), last.isoformat())
            )
        }
    count = 0
    current = first
    while current <= last:
        if current.weekday() < 5 and current.isoformat() not in holidays:
            count += 1
        current += timedelta(days=1)
    return count


def get_balance(employee_id: str, leave_type: str, year: int,
                db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Return entitlement, used, pending, remaining and available days for one employee/type/year."""
    if leave_type not in ("annual", "sick", "comp_off"):
        raise LeaveError("Balances are available only for annual, sick, and comp_off leave.")

    with connection(db_path) as conn:
        if leave_type in ("annual", "sick"):
            row = conn.execute(
                """SELECT entitled_days, used_days FROM leave_balances
                   WHERE employee_id = ? AND leave_type = ? AND year = ?""",
                (employee_id, leave_type, year),
            ).fetchone()
            if row is None:
                raise LeaveError(f"No {leave_type} balance found for {employee_id} in {year}.")

            pending_row = conn.execute(
                """SELECT COALESCE(SUM(requested_days), 0.0) as pending_days
                   FROM leave_requests
                   WHERE employee_id = ? AND leave_type = ? AND status IN ('pending', 'needs_review')
                   AND strftime('%Y', start_date) = ?""",
                (employee_id, leave_type, str(year)),
            ).fetchone()
            pending_days = float(pending_row["pending_days"]) if pending_row else 0.0
            ent = float(row["entitled_days"])
            used = float(row["used_days"])
            rem = round(ent - used, 2)
            avail = round(max(0.0, rem - pending_days), 2)
            return {
                "employee_id": employee_id, "leave_type": leave_type, "year": year,
                "entitled_days": ent,
                "used_days": used,
                "pending_days": pending_days,
                "remaining_days": rem,
                "available_days": avail,
            }
        else: # comp_off
            earned_row = conn.execute(
                """SELECT COALESCE(SUM(days), 0.0) as earned_days
                   FROM comp_off_records
                   WHERE employee_id = ? AND strftime('%Y', earned_on) = ?""",
                (employee_id, str(year))
            ).fetchone()
            earned = float(earned_row["earned_days"]) if earned_row else 0.0

            used_row = conn.execute(
                """SELECT COALESCE(SUM(days), 0.0) as used_days
                   FROM comp_off_records
                   WHERE employee_id = ? AND status = 'used' AND strftime('%Y', used_on) = ?""",
                (employee_id, str(year))
            ).fetchone()
            used = float(used_row["used_days"]) if used_row else 0.0

            today_str = date.today().isoformat()
            avail_row = conn.execute(
                """SELECT COALESCE(SUM(days), 0.0) as remaining_days
                   FROM comp_off_records
                   WHERE employee_id = ? AND status = 'available' AND expires_on >= ?""",
                (employee_id, today_str)
            ).fetchone()
            rem = float(avail_row["remaining_days"]) if avail_row else 0.0

            pending_row = conn.execute(
                """SELECT COALESCE(SUM(requested_days), 0.0) as pending_days
                   FROM leave_requests
                   WHERE employee_id = ? AND leave_type = 'comp_off' AND status IN ('pending', 'needs_review')
                   AND strftime('%Y', start_date) = ?""",
                (employee_id, str(year))
            ).fetchone()
            pending_days = float(pending_row["pending_days"]) if pending_row else 0.0
            avail = round(max(0.0, rem - pending_days), 2)
            return {
                "employee_id": employee_id, "leave_type": "comp_off", "year": year,
                "entitled_days": earned,
                "used_days": used,
                "pending_days": pending_days,
                "remaining_days": rem,
                "available_days": avail,
            }


def _check_employee(conn: sqlite3.Connection, employee_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT employee_id, role, team_id, is_active FROM employees WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()
    if row is None or not row["is_active"]:
        raise LeaveError("Employee does not exist or is inactive.")
    return row


def _calculate_days(conn: sqlite3.Connection, start: date, end: date,
                    leave_type: str, exclude_optional_holidays: bool = False) -> int:
    if end < start:
        raise LeaveError("End date cannot be before start date.")
    holiday_types = ("public", "optional") if exclude_optional_holidays else ("public",)
    placeholders = ",".join("?" for _ in holiday_types)
    holidays = {
        row["date"] for row in conn.execute(
            f"SELECT date FROM holidays WHERE holiday_type IN ({placeholders}) "
            f"AND date BETWEEN ? AND ?", (*holiday_types, start.isoformat(), end.isoformat())
        )
    }
    count, day = 0, start
    while day <= end:
        if day.weekday() < 5 and day.isoformat() not in holidays:
            count += 1
        day += timedelta(days=1)
    return count


def create_leave_request(employee_id: str, leave_type: LeaveType,
                         start_date: Union[str, date], end_date: Union[str, date],
                         reason: str = "", submitted_on: Optional[Union[str, date]] = None,
                         db_path: Path = DB_PATH,
                         exclude_optional_holidays: bool = False) -> int:
    """Create a pending request after deterministic validation; returns request ID."""
    if leave_type not in ("annual", "sick", "comp_off"):
        raise LeaveError("leave_type must be annual, sick, or comp_off.")
    start, end = _as_date(start_date), _as_date(end_date)
    submitted = _as_date(submitted_on or date.today())
    if end < start:
        raise LeaveError("End date cannot be before start date.")
    if start < submitted:
        raise LeaveError("Leave start date cannot be in the past.")
    if leave_type in ("annual", "sick") and start.year != end.year:
        raise LeaveError("Annual and sick leave requests cannot cross calendar years; split the request.")
    if leave_type == "annual" and (start - submitted).days < 5:
        raise LeaveError("Annual leave must be requested at least 5 calendar days in advance.")

    with connection(db_path) as conn:
        employee = _check_employee(conn, employee_id)
        if employee["role"] != "employee":
            raise LeaveError("Only employee accounts can submit leave requests.")

        # Check duplicate identical request
        duplicate = conn.execute(
            """SELECT request_id FROM leave_requests
               WHERE employee_id = ? AND start_date = ? AND end_date = ? AND leave_type = ?
                 AND status IN ('pending', 'needs_review', 'approved')""",
            (employee_id, start.isoformat(), end.isoformat(), leave_type),
        ).fetchone()
        if duplicate:
            raise LeaveError(f"Duplicate {leave_type} leave request #{duplicate['request_id']} already exists for these dates.")

        days = _calculate_days(conn, start, end, leave_type, exclude_optional_holidays=exclude_optional_holidays)
        if days <= 0:
            raise LeaveError("The selected date range contains no chargeable working days.")

        overlap = conn.execute(
            """SELECT request_id FROM leave_requests
               WHERE employee_id = ? AND status IN ('pending','needs_review','approved')
                 AND NOT (end_date < ? OR start_date > ?)""",
            (employee_id, start.isoformat(), end.isoformat()),
        ).fetchone()
        if overlap:
            raise LeaveError(f"Dates overlap with existing request #{overlap['request_id']}.")

        if leave_type in ("annual", "sick"):
            balance = conn.execute(
                """SELECT entitled_days, used_days FROM leave_balances
                   WHERE employee_id=? AND leave_type=? AND year=?""",
                (employee_id, leave_type, start.year),
            ).fetchone()
            if balance is None:
                raise LeaveError(f"No {leave_type} balance exists for {start.year}.")
            # Pending requests are not deducted here; approval rechecks balance.
            remaining = float(balance["entitled_days"]) - float(balance["used_days"])
            if days > remaining:
                raise LeaveError(f"Insufficient {leave_type} balance: {remaining:g} day(s) remain.")

        if leave_type == "comp_off":
            available_row = conn.execute(
                """SELECT COALESCE(SUM(days),0) FROM comp_off_records
                   WHERE employee_id=? AND status='available' AND expires_on >= ?""",
                (employee_id, submitted.isoformat()),
            ).fetchone()
            available = float(available_row[0]) if available_row else 0.0

            pending_row = conn.execute(
                """SELECT COALESCE(SUM(requested_days), 0.0) FROM leave_requests
                   WHERE employee_id=? AND leave_type='comp_off' AND status IN ('pending', 'needs_review')""",
                (employee_id,)
            ).fetchone()
            pending = float(pending_row[0]) if pending_row else 0.0
            unreserved = max(0.0, available - pending)
            if days > unreserved:
                raise LeaveError(
                    f"Insufficient unreserved comp-off: {unreserved:g} day(s) available ({pending:g} day(s) already reserved in pending requests)."
                )

        approval_due = (submitted + timedelta(days=3)).isoformat()
        cursor = conn.execute(
            """INSERT INTO leave_requests
               (employee_id, leave_type, start_date, end_date, requested_days,
                reason, status, submitted_on, approval_due_on)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (employee_id, leave_type, start.isoformat(), end.isoformat(),
             days, reason.strip() or None, submitted.isoformat(),
             approval_due),
        )
        rid = int(cursor.lastrowid)

        # Automatic generation of required timeline approval deadline
        conn.execute(
            """INSERT INTO timeline_items
               (title, due_on, item_type, employee_id, team_id, details, priority, status, reminder_date, created_by)
               VALUES (?, ?, 'approval_deadline', ?, ?, ?, 'high', 'active', ?, ?)""",
            (f"Approval deadline for request #{rid} ({employee_id})",
             approval_due,
             employee_id,
             employee["team_id"],
             f"Pending {leave_type} leave review ({start} to {end})",
             (submitted + timedelta(days=2)).isoformat(),
             employee_id)
        )
    log_audit(employee_id, employee["role"], "create_leave_request", str(rid),
              f"Submitted {leave_type} leave for {days} day(s) ({start} to {end})", db_path)
    return rid


def _consume_comp_off(conn: sqlite3.Connection, employee_id: str,
                      days_needed: float, decision_date: date) -> None:
    records = conn.execute(
        """SELECT comp_off_id, days FROM comp_off_records
           WHERE employee_id=? AND status='available' AND expires_on >= ?
           ORDER BY expires_on, earned_on, comp_off_id""",
        (employee_id, decision_date.isoformat()),
    ).fetchall()
    remaining = days_needed
    for record in records:
        if remaining <= 0:
            break
        record_days = float(record["days"])
        if record_days <= remaining:
            conn.execute(
                """UPDATE comp_off_records SET status='used', used_on=?
                   WHERE comp_off_id=? AND status='available'""",
                (decision_date.isoformat(), record["comp_off_id"]),
            )
            remaining -= record_days
        else:
            # Schema has no partial-use ledger; do not split a comp-off record.
            raise LeaveError("Comp-off must be used in whole record units; partial record use is unsupported.")
    if remaining > 0:
        raise LeaveError("Not enough unexpired comp-off records remain at approval time.")


def decide_leave_request(request_id: Any, decision: Any,
                         decided_by: Any = None, note: str = "",
                         decided_on: Optional[Union[str, date]] = None,
                         db_path: Path = DB_PATH) -> None:
    """Manager/HR decision. Approved leave atomically updates the relevant balance."""
    from access_control.service import AccessError
    if hasattr(request_id, "employee_id"):
        actual_actor = request_id
        actual_req_id = int(decision)
        actual_decision = str(decided_by)
        actual_decided_by = actual_actor.employee_id
        actual_note = note
        actual_decided_on = decided_on
        actual_db_path = db_path
    else:
        actual_req_id = int(request_id)
        actual_decision = str(decision)
        actual_decided_by = decided_by.employee_id if hasattr(decided_by, "employee_id") else str(decided_by)
        actual_note = note
        actual_decided_on = decided_on
        actual_db_path = db_path

    if actual_decision not in ("approved", "declined"):
        raise LeaveError("Decision must be approved or declined.")
    request_id = actual_req_id
    decision = actual_decision
    decided_by = actual_decided_by
    db_path = actual_db_path
    decision_day = _as_date(actual_decided_on or date.today())
    with connection(actual_db_path) as conn:
        actor = _check_employee(conn, actual_decided_by)
        if actor["role"] not in ("manager", "hr"):
            raise LeaveError("Only a manager or HR user may decide leave requests.")
        request = conn.execute(
            "SELECT lr.*, e.team_id AS employee_team_id FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id WHERE lr.request_id=?", (actual_req_id,)
        ).fetchone()
        if request is not None and actor["role"] == "manager" and request["employee_team_id"] != conn.execute("SELECT team_id FROM employees WHERE employee_id=?", (actual_decided_by,)).fetchone()["team_id"]:
            raise LeaveError("Managers may decide requests only for their own team.")
        if request is None:
            raise LeaveError(f"Leave request #{actual_req_id} does not exist.")
        if request["status"] not in ("pending", "needs_review"):
            raise LeaveError("Only pending or needs_review requests can be decided.")

        if decision == "approved":
            kind = request["leave_type"]
            days = float(request["requested_days"])
            if kind in ("annual", "sick"):
                year = _as_date(request["start_date"]).year
                balance = conn.execute(
                    """SELECT entitled_days, used_days FROM leave_balances
                       WHERE employee_id=? AND leave_type=? AND year=?""",
                    (request["employee_id"], kind, year),
                ).fetchone()
                if balance is None or days > float(balance["entitled_days"]) - float(balance["used_days"]):
                    raise LeaveError(f"Insufficient {kind} balance at approval time.")
                conn.execute(
                    """UPDATE leave_balances SET used_days=used_days+?
                       WHERE employee_id=? AND leave_type=? AND year=?""",
                    (days, request["employee_id"], kind, year),
                )
            elif kind == "comp_off":
                _consume_comp_off(conn, request["employee_id"], days, decision_day)
            conn.execute(
                """UPDATE leave_requests SET status='approved', decided_by=?, decided_on=?
                   WHERE request_id=?""",
                (decided_by, decision_day.isoformat(), request_id),
            )
            conn.execute(
                """INSERT INTO attendance(employee_id,date,status)
                   SELECT ?, d, 'approved_leave'
                   FROM (
                     WITH RECURSIVE dates(d) AS (
                       SELECT ? UNION ALL SELECT date(d, '+1 day') FROM dates WHERE d < ?
                     ) SELECT d FROM dates
                   )
                   WHERE strftime('%w', d) NOT IN ('0','6')
                     AND NOT EXISTS (SELECT 1 FROM holidays h WHERE h.date=d AND h.holiday_type='public')
                   ON CONFLICT(employee_id,date) DO UPDATE SET status='approved_leave'""",
                (request["employee_id"], request["start_date"], request["end_date"]),
            )

            # Mark approval deadline completed
            conn.execute(
                """UPDATE timeline_items SET status='completed'
                   WHERE title LIKE ? AND item_type='approval_deadline'""",
                (f"%request #{request_id}%",)
            )

            # Calculate expected return-to-work date and automatically generate return_to_work timeline item
            cur_d = _as_date(request["end_date"]) + timedelta(days=1)
            pub_hols = {
                r["date"] for r in conn.execute(
                    "SELECT date FROM holidays WHERE holiday_type='public' AND date >= ?",
                    (cur_d.isoformat(),)
                ).fetchall()
            }
            while cur_d.weekday() >= 5 or cur_d.isoformat() in pub_hols:
                cur_d += timedelta(days=1)
            return_work_day = cur_d.isoformat()

            conn.execute(
                """INSERT INTO timeline_items
                   (title, due_on, item_type, employee_id, team_id, details, priority, status, created_by)
                   VALUES (?, ?, 'return_to_work', ?, ?, ?, 'normal', 'active', ?)""",
                (f"Return to work: {request['employee_id']} ({request['leave_type']} leave)",
                 return_work_day, request["employee_id"], request["employee_team_id"],
                 f"Expected return after leave from {request['start_date']} to {request['end_date']}",
                 decided_by),
            )
        else:
            conn.execute(
                """UPDATE leave_requests SET status='declined', decided_by=?, decided_on=?
                   WHERE request_id=?""",
                (decided_by, decision_day.isoformat(), request_id),
            )
            # Mark approval deadline cancelled
            conn.execute(
                """UPDATE timeline_items SET status='cancelled'
                   WHERE title LIKE ? AND item_type='approval_deadline'""",
                (f"%request #{request_id}%",)
            )
        conn.execute(
            """INSERT INTO decision_history
               (request_id, recommendation, evidence_json, final_decision, decided_by, decided_on, note)
               VALUES (?, ?, '{}', ?, ?, ?, ?)""",
            (request_id, "manual_manager_or_hr_decision", decision, decided_by,
             decision_day.isoformat(), note.strip() or None),
        )
    log_audit(decided_by, actor["role"], f"leave_decision_{decision}", str(request_id),
              f"Decision {decision} for request #{request_id} (employee {request['employee_id']}) with note: {note}", db_path)


def cancel_leave_request(actor: UserContext, request_id: int, reason: str = "",
                         db_path: Path = DB_PATH) -> None:
    """Allow an employee to cancel their pending or approved leave request.

    If the request was approved, restores used leave balance and clears the approved leave
    from attendance records.
    """
    with connection(db_path) as conn:
        req = conn.execute(
            """SELECT lr.*, e.team_id FROM leave_requests lr
               JOIN employees e ON e.employee_id = lr.employee_id
               WHERE lr.request_id = ?""",
            (request_id,)
        ).fetchone()
        if not req:
            raise LeaveError(f"Leave request #{request_id} not found.")

        # Access check: Requester, same-team manager, or HR
        if actor.role == "employee" and actor.employee_id != req["employee_id"]:
            raise LeaveError("Employees can only cancel their own leave requests.")
        if actor.role == "manager" and actor.team_id != req["team_id"]:
            raise LeaveError("Managers can only cancel requests for their own team.")

        status = req["status"]
        if status in ("declined", "cancelled"):
            raise LeaveError(f"Request #{request_id} is already {status}.")

        # If already approved, restore balance and clean up attendance
        if status == "approved":
            kind = req["leave_type"]
            days = float(req["requested_days"])
            emp_id = req["employee_id"]
            if kind in ("annual", "sick"):
                year = _as_date(req["start_date"]).year
                conn.execute(
                    """UPDATE leave_balances SET used_days = MAX(0, used_days - ?)
                       WHERE employee_id = ? AND leave_type = ? AND year = ?""",
                    (days, emp_id, kind, year)
                )
            elif kind == "comp_off":
                # Restore used comp-off record(s)
                conn.execute(
                    """UPDATE comp_off_records SET status = 'available', used_on = NULL
                       WHERE employee_id = ? AND status = 'used' AND days <= ?""",
                    (emp_id, days)
                )
            # Remove approved_leave from attendance for the leave span
            conn.execute(
                """DELETE FROM attendance WHERE employee_id = ? AND date BETWEEN ? AND ?
                   AND status = 'approved_leave'""",
                (emp_id, req["start_date"], req["end_date"])
            )

        cancel_note = f"Cancelled by {actor.employee_id} ({actor.role}): {reason.strip()}".strip()
        conn.execute(
            """UPDATE leave_requests SET status = 'declined', decided_by = ?, decided_on = ?
               WHERE request_id = ?""",
            (actor.employee_id, date.today().isoformat(), request_id)
        )
        conn.execute(
            """UPDATE timeline_items SET status = 'cancelled'
               WHERE (title LIKE ? OR details LIKE ?) AND employee_id = ?""",
            (f"%request #{request_id}%", f"%request #{request_id}%", req["employee_id"])
        )
        conn.execute(
            """INSERT INTO decision_history
               (request_id, recommendation, evidence_json, final_decision, decided_by, decided_on, note)
               VALUES (?, 'cancelled_by_user', '{}', 'declined', ?, ?, ?)""",
            (request_id, actor.employee_id, date.today().isoformat(), cancel_note)
        )
    log_audit(actor.employee_id, actor.role, "cancel_leave_request", str(request_id),
              f"Cancelled leave request #{request_id} for {req['employee_id']}", db_path)
    return {
        "request_id": request_id,
        "employee_id": req["employee_id"],
        "status": "declined",
        "cancelled": True,
        "message": f"Request #{request_id} cancelled successfully."
    }


def list_leave_requests(actor: UserContext, employee_id: Optional[str] = None,
                        status: Optional[str] = None, leave_type: Optional[str] = None,
                        db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """List leave requests with role-based scope enforcement."""
    with connection(db_path) as conn:
        query = """SELECT lr.*, e.name as employee_name, e.team_id, t.name as team_name
                   FROM leave_requests lr
                   JOIN employees e ON e.employee_id = lr.employee_id
                   JOIN teams t ON t.team_id = e.team_id WHERE 1=1"""
        params: List[Any] = []
        if actor.role == "employee":
            query += " AND lr.employee_id = ?"
            params.append(actor.employee_id)
        elif actor.role == "manager":
            query += " AND e.team_id = ?"
            params.append(actor.team_id)
            if employee_id:
                query += " AND lr.employee_id = ?"
                params.append(employee_id)
        else:
            if employee_id:
                query += " AND lr.employee_id = ?"
                params.append(employee_id)

        if status:
            query += " AND lr.status = ?"
            params.append(status)
        if leave_type:
            query += " AND lr.leave_type = ?"
            params.append(leave_type)

        query += " ORDER BY lr.submitted_on DESC, lr.request_id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def refresh_comp_off_status(as_of: Optional[Union[str, date]] = None,
                            db_path: Path = DB_PATH) -> int:
    """Mark available records expired on/before as_of; return number changed."""
    day = _as_date(as_of or date.today())
    with connection(db_path) as conn:
        cursor = conn.execute(
            """UPDATE comp_off_records SET status='expired'
               WHERE status='available' AND expires_on < ?""",
            (day.isoformat(),),
        )
        return cursor.rowcount


def list_holidays(start_date: Union[str, date], end_date: Union[str, date],
                  db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    start, end = _as_date(start_date), _as_date(end_date)
    if end < start:
        raise LeaveError("End date cannot be before start date.")
    with connection(db_path) as conn:
        rows = conn.execute(
            """SELECT holiday_id, date, name, holiday_type FROM holidays
               WHERE date BETWEEN ? AND ? ORDER BY date""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(row) for row in rows]


def add_holiday(holiday_date: Union[str, date], name: str, holiday_type: str,
                db_path: Path = DB_PATH) -> int:
    """Add a public or optional holiday. Duplicate dates are rejected by SQLite."""
    day = _as_date(holiday_date)
    if not name.strip():
        raise LeaveError("Holiday name is required.")
    if holiday_type not in ("public", "optional"):
        raise LeaveError("holiday_type must be public or optional.")
    with connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO holidays(date,name,holiday_type) VALUES (?,?,?)",
            (day.isoformat(), name.strip(), holiday_type),
        )
        hid = int(cursor.lastrowid)
    log_audit("system", "hr", "add_holiday", str(hid), f"Added {holiday_type} holiday '{name}' on {day}", db_path)
    return hid


def get_optional_holidays_in_range(start_date: Union[str, date], end_date: Union[str, date],
                                   db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Return all optional holidays within the given date range for employee selection."""
    start, end = _as_date(start_date), _as_date(end_date)
    with connection(db_path) as conn:
        rows = conn.execute(
            """SELECT holiday_id, date, name, holiday_type FROM holidays
               WHERE holiday_type = 'optional' AND date BETWEEN ? AND ? ORDER BY date""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [dict(r) for r in rows]


def get_calendar_breakdown(start_date: Union[str, date], end_date: Union[str, date],
                           db_path: Path = DB_PATH,
                           exclude_optional_holidays: bool = False) -> List[Dict[str, Any]]:
    """Return a detailed day-by-day classification for a date range:
    identifies weekends, public holidays, optional holidays, and chargeable working days.
    """
    first, last = _as_date(start_date), _as_date(end_date)
    if last < first:
        raise LeaveError("End date cannot be before start date.")

    with connection(db_path) as conn:
        holidays_map = {
            r["date"]: {"name": r["name"], "holiday_type": r["holiday_type"]}
            for r in conn.execute(
                "SELECT date, name, holiday_type FROM holidays WHERE date BETWEEN ? AND ?",
                (first.isoformat(), last.isoformat())
            ).fetchall()
        }

    days_list = []
    cur = first
    days_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    while cur <= last:
        d_str = cur.isoformat()
        is_wknd = cur.weekday() >= 5
        hol = holidays_map.get(d_str)
        is_pub = hol["holiday_type"] == "public" if hol else False
        is_opt = hol["holiday_type"] == "optional" if hol else False

        if is_wknd:
            status = "Weekend"
            is_work = False
        elif is_pub:
            status = "Public Holiday"
            is_work = False
        elif is_opt and exclude_optional_holidays:
            status = "Optional Holiday (Claimed)"
            is_work = False
        elif is_opt:
            status = "Optional Holiday (Normal Working Day)"
            is_work = True
        else:
            status = "Working Day"
            is_work = True

        days_list.append({
            "date": d_str,
            "day_of_week": days_names[cur.weekday()],
            "is_weekend": is_wknd,
            "is_public_holiday": is_pub,
            "is_optional_holiday": is_opt,
            "holiday_name": hol["name"] if hol else None,
            "holiday_type": hol["holiday_type"] if hol else None,
            "is_working_day": is_work,
            "status_label": status
        })
        cur += timedelta(days=1)

    return days_list


def explain_leave_interaction(leave_type: str, start_date: Union[str, date], end_date: Union[str, date],
                              employee_id: Optional[str] = None,
                              exclude_optional_holidays: bool = False,
                              db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Explain how a proposed leave request interacts with public holidays, optional holidays, and comp-off.

    Surfaces:
    - Calendar day breakdown
    - Public holidays excluded from balance deduction
    - Optional holidays claimed or working
    - Comp-off credits consumed (FIFO order by expiry) and expiring credits
    - Balance impact before and after
    - Plain-language explanation for employee and manager transparency
    """
    first, last = _as_date(start_date), _as_date(end_date)
    if last < first:
        raise LeaveError("End date cannot be before start date.")

    calendar_days = get_calendar_breakdown(first, last, db_path, exclude_optional_holidays)
    total_calendar = len(calendar_days)
    weekend_days = sum(1 for d in calendar_days if d["is_weekend"])
    public_hols = [d for d in calendar_days if d["is_public_holiday"]]
    optional_hols = [d for d in calendar_days if d["is_optional_holiday"]]
    chargeable = sum(1 for d in calendar_days if d["is_working_day"])

    explanations = [
        f"Total calendar duration: {total_calendar} day(s) from {first} to {last}."
    ]

    if weekend_days:
        explanations.append(f"{weekend_days} weekend day(s) are excluded from leave charges.")
    if public_hols:
        hol_names = ", ".join(f"{h['holiday_name']} on {h['date']}" for h in public_hols)
        explanations.append(f"Public holiday(s) falling in the period ({hol_names}) are not charged against your leave balance.")
    if optional_hols:
        if exclude_optional_holidays:
            explanations.append(f"Optional holiday claim active: {len(optional_hols)} optional holiday(s) excluded from charged leave.")
        else:
            explanations.append(f"{len(optional_hols)} optional holiday(s) occur in this span and will count as working days unless claimed.")

    comp_off_info = None
    balance_info = None

    if employee_id:
        with connection(db_path) as conn:
            if leave_type == "comp_off":
                avail_records = conn.execute(
                    """SELECT comp_off_id, earned_on, expires_on, days, work_reference
                       FROM comp_off_records
                       WHERE employee_id=? AND status='available' AND expires_on >= ?
                       ORDER BY expires_on, earned_on, comp_off_id""",
                    (employee_id, date.today().isoformat())
                ).fetchall()
                records_list = [dict(r) for r in avail_records]
                total_avail = sum(r["days"] for r in records_list)

                # Pending comp-off
                pending_row = conn.execute(
                    """SELECT COALESCE(SUM(requested_days), 0.0) FROM leave_requests
                       WHERE employee_id=? AND leave_type='comp_off' AND status IN ('pending', 'needs_review')""",
                    (employee_id,)
                ).fetchone()
                pending_days = float(pending_row[0]) if pending_row else 0.0
                unreserved = max(0.0, total_avail - pending_days)

                # FIFO consumption simulation
                rem = chargeable
                to_consume = []
                for r in records_list:
                    if rem <= 0:
                        break
                    r_days = float(r["days"])
                    to_consume.append({
                        "comp_off_id": r["comp_off_id"],
                        "earned_on": r["earned_on"],
                        "expires_on": r["expires_on"],
                        "days": r_days,
                        "work_reference": r["work_reference"]
                    })
                    rem -= r_days

                comp_off_info = {
                    "total_available_days": total_avail,
                    "pending_requested_days": pending_days,
                    "unreserved_days": unreserved,
                    "chargeable_days": chargeable,
                    "is_sufficient": unreserved >= chargeable,
                    "records_to_consume": to_consume
                }
                if unreserved >= chargeable:
                    explanations.append(f"Comp-off balance is sufficient: {chargeable} day(s) will be consumed from {len(to_consume)} credit record(s) in earliest-expiry order.")
                else:
                    explanations.append(f"Insufficient comp-off: Requires {chargeable} day(s), but only {unreserved:g} unreserved day(s) remain.")

            elif leave_type in ("annual", "sick"):
                year = first.year
                bal_row = conn.execute(
                    "SELECT entitled_days, used_days FROM leave_balances WHERE employee_id=? AND leave_type=? AND year=?",
                    (employee_id, leave_type, year)
                ).fetchone()
                if bal_row:
                    ent = float(bal_row["entitled_days"])
                    usd = float(bal_row["used_days"])
                    rem = round(ent - usd, 2)
                    balance_info = {
                        "entitled_days": ent,
                        "used_days": usd,
                        "remaining_days": rem,
                        "projected_remaining_after_approval": round(rem - chargeable, 2),
                        "is_sufficient": rem >= chargeable
                    }
                    if rem >= chargeable:
                        explanations.append(f"{leave_type.capitalize()} balance is sufficient ({rem} remaining, {chargeable} requested).")
                    else:
                        explanations.append(f"Insufficient {leave_type} balance ({rem} remaining, {chargeable} requested).")

    explanations.append(f"Final chargeable working days: {chargeable} day(s).")

    return {
        "leave_type": leave_type,
        "start_date": first.isoformat(),
        "end_date": last.isoformat(),
        "total_calendar_days": total_calendar,
        "weekend_days": weekend_days,
        "public_holidays": public_hols,
        "optional_holidays": optional_hols,
        "chargeable_working_days": chargeable,
        "calendar_breakdown": calendar_days,
        "comp_off_info": comp_off_info,
        "balance_info": balance_info,
        "explanation_summary": " ".join(explanations)
    }

