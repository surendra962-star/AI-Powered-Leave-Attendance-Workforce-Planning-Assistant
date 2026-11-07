"""Structured timeline and alert queries. Dates are ISO local calendar dates.
Alerts are in-app records; no email/SMS integration is implied.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional, List, Dict, Any, Union
from database.db import DB_PATH, connection, log_audit
from access_control.service import UserContext, require_role


def _scope(actor: UserContext, employee_id: Optional[str], db_path):
    if actor.role == 'hr':
        return
    if actor.role == 'employee':
        if employee_id not in (None, actor.employee_id):
            raise PermissionError('Employees may view only their own timeline.')
        return
    if employee_id:
        with connection(db_path) as c:
            row = c.execute('SELECT team_id FROM employees WHERE employee_id=? AND is_active=1', (employee_id,)).fetchone()
        if not row or row['team_id'] != actor.team_id:
            raise PermissionError('Outside manager team scope.')


def add_timeline_item(actor: UserContext, title: str, due_on: str, item_type: str,
                      employee_id: Optional[str] = None, details: str = '',
                      priority: str = 'normal', reminder_date: Optional[str] = None,
                      db_path=DB_PATH) -> int:
    require_role(actor, 'manager', 'hr')
    if item_type not in {'project_deadline', 'approval_deadline', 'return_to_work', 'notice_deadline', 'other'}:
        raise ValueError('Unsupported timeline item type.')
    if priority not in {'low', 'normal', 'high', 'critical'}:
        raise ValueError('Unsupported priority level.')
    if not title.strip():
        raise ValueError('Title is required.')
    date.fromisoformat(due_on)
    if reminder_date:
        date.fromisoformat(reminder_date)
    with connection(db_path) as c:
        row = None
        if employee_id:
            row = c.execute('SELECT team_id,is_active FROM employees WHERE employee_id=?', (employee_id,)).fetchone()
            if not row or not row['is_active']:
                raise ValueError('Employee not found or inactive.')
            if actor.role == 'manager' and row['team_id'] != actor.team_id:
                raise PermissionError('Outside manager team scope.')
        team_id = actor.team_id if actor.role == 'manager' else (row['team_id'] if employee_id and row else None)
        cur = c.execute('''INSERT INTO timeline_items
            (title, due_on, item_type, employee_id, team_id, details, priority, status, reminder_date, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)''',
            (title.strip(), due_on, item_type, employee_id, team_id, details.strip(), priority, reminder_date, actor.employee_id))
        item_id = int(cur.lastrowid)
    log_audit(actor.employee_id, actor.role, "create_timeline_item", str(item_id), f"Created {item_type}: {title.strip()}", db_path)
    return item_id


def update_timeline_item(actor: UserContext, item_id: int, status: str = 'completed',
                         db_path=DB_PATH) -> None:
    """Manager/HR status update for a timeline item (active, completed, cancelled)."""
    require_role(actor, 'manager', 'hr')
    if status not in {'active', 'completed', 'cancelled'}:
        raise ValueError('Invalid timeline status.')
    with connection(db_path) as c:
        item = c.execute("SELECT team_id FROM timeline_items WHERE item_id=?", (item_id,)).fetchone()
        if not item:
            raise ValueError(f"Timeline item {item_id} not found.")
        if actor.role == 'manager' and item['team_id'] and item['team_id'] != actor.team_id:
            raise PermissionError("Outside manager team scope.")
        c.execute("UPDATE timeline_items SET status=? WHERE item_id=?", (status, item_id))
    log_audit(actor.employee_id, actor.role, "update_timeline_status", str(item_id), f"Status updated to {status}", db_path)


def list_timeline(actor: UserContext, start_date: str, end_date: str,
                  employee_id: Optional[str] = None, status: Optional[str] = None,
                  db_path=DB_PATH) -> List[Dict[str, Any]]:
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if end < start:
        raise ValueError('End date must not precede start date.')
    _scope(actor, employee_id, db_path)
    with connection(db_path) as c:
        sql = '''SELECT ti.*, e.name AS employee_name FROM timeline_items ti
               LEFT JOIN employees e ON e.employee_id=ti.employee_id
               WHERE ti.due_on BETWEEN ? AND ?'''
        p: List[Any] = [start.isoformat(), end.isoformat()]
        if status:
            sql += ' AND ti.status=?'
            p.append(status)
        if actor.role == 'employee':
            sql += ' AND (ti.employee_id=? OR ti.employee_id IS NULL)'
            p.append(actor.employee_id)
        elif actor.role == 'manager':
            sql += ' AND (ti.team_id=? OR ti.employee_id IN (SELECT employee_id FROM employees WHERE team_id=?))'
            p += [actor.team_id, actor.team_id]
        elif employee_id:
            sql += ' AND ti.employee_id=?'
            p.append(employee_id)
        sql += ' ORDER BY ti.due_on, ti.item_id'
        return [dict(x) for x in c.execute(sql, p)]


def _as_date(val: Union[str, date]) -> date:
    if isinstance(val, date):
        return val
    return date.fromisoformat(val)


def calculate_return_to_work_date(end_date: Union[str, date], db_path: Path = DB_PATH) -> date:
    """Calculate the expected return-to-work date: next working day following end_date.

    Skips weekends (Saturday, Sunday) and designated public holidays.
    """
    cur = _as_date(end_date) + timedelta(days=1)
    with connection(db_path) as conn:
        pub_holidays = {
            r["date"] for r in conn.execute(
                "SELECT date FROM holidays WHERE holiday_type='public' AND date >= ?",
                (cur.isoformat(),)
            ).fetchall()
        }
    while cur.weekday() >= 5 or cur.isoformat() in pub_holidays:
        cur += timedelta(days=1)
    return cur


def get_alerts(actor: UserContext, as_of: Optional[str] = None, horizon_days: int = 30,
               db_path=DB_PATH) -> List[Dict[str, Any]]:
    today = date.fromisoformat(as_of) if as_of else date.today()
    if horizon_days < 0 or horizon_days > 366:
        raise ValueError('horizon_days must be 0..366.')
    end = today + timedelta(days=horizon_days)
    alerts = []
    with connection(db_path) as c:
        # 1. Leave approval deadlines (pending/needs_review)
        sql = '''SELECT lr.request_id, lr.employee_id, e.name, lr.approval_due_on, lr.start_date, lr.end_date, lr.status
               FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id
               WHERE lr.status IN ('pending','needs_review') AND lr.approval_due_on IS NOT NULL'''
        p: List[Any] = []
        if actor.role == 'employee':
            sql += ' AND lr.employee_id=?'
            p.append(actor.employee_id)
        elif actor.role == 'manager':
            sql += ' AND e.team_id=?'
            p.append(actor.team_id)
        for r in c.execute(sql, p):
            due = date.fromisoformat(r['approval_due_on'])
            if due <= end:
                alerts.append({
                    'type': 'approval_overdue' if due < today else 'approval_due',
                    'severity': 'high' if due < today else 'medium',
                    'due_on': due.isoformat(),
                    'message': f"Approval for request #{r['request_id']} ({r['name']}) is {'overdue' if due < today else 'due soon'}"
                })

        # 2. Comp-off records expiring soon
        comp_sql = "SELECT employee_id, comp_off_id, expires_on, days FROM comp_off_records WHERE status='available' AND expires_on<=?"
        comp_p = [end.isoformat()]
        if actor.role == 'employee':
            comp_sql += ' AND employee_id=?'
            comp_p.append(actor.employee_id)
        elif actor.role == 'manager':
            comp_sql += ' AND employee_id IN (SELECT employee_id FROM employees WHERE team_id=?)'
            comp_p.append(actor.team_id)
        for r in c.execute(comp_sql, comp_p):
            exp_date = date.fromisoformat(r['expires_on'])
            if exp_date >= today:
                days_left = (exp_date - today).days
                alerts.append({
                    'type': 'comp_off_expiry',
                    'severity': 'high' if days_left <= 7 else 'medium',
                    'due_on': r['expires_on'],
                    'message': f"{r['days']} comp-off day(s) for {r['employee_id']} expire on {r['expires_on']} ({days_left} day(s) remaining)"
                })

        # 3. Expired comp-off records requiring refresh
        exp_sql = "SELECT employee_id, comp_off_id, expires_on, days FROM comp_off_records WHERE status='available' AND expires_on < ?"
        exp_p = [today.isoformat()]
        if actor.role == 'employee':
            exp_sql += ' AND employee_id=?'
            exp_p.append(actor.employee_id)
        elif actor.role == 'manager':
            exp_sql += ' AND employee_id IN (SELECT employee_id FROM employees WHERE team_id=?)'
            exp_p.append(actor.team_id)
        for r in c.execute(exp_sql, exp_p):
            alerts.append({
                'type': 'comp_off_expired',
                'severity': 'high',
                'due_on': r['expires_on'],
                'message': f"{r['days']} comp-off day(s) for {r['employee_id']} expired on {r['expires_on']} (needs refresh)"
            })

        # 4. Critical project deadlines missing backup assignments
        crit_sql = """SELECT pd.deadline_id, pd.title, pd.due_on, pd.owner_id, e.name as owner_name, pd.team_id
                      FROM project_deadlines pd
                      JOIN employees e ON e.employee_id = pd.owner_id
                      LEFT JOIN backup_assignments ba ON ba.deadline_id = pd.deadline_id
                      WHERE pd.critical = 1 AND ba.backup_employee_id IS NULL AND pd.due_on BETWEEN ? AND ?"""
        crit_p = [today.isoformat(), end.isoformat()]
        if actor.role == 'employee':
            crit_sql += ' AND pd.owner_id=?'
            crit_p.append(actor.employee_id)
        elif actor.role == 'manager':
            crit_sql += ' AND pd.team_id=?'
            crit_p.append(actor.team_id)
        for d in c.execute(crit_sql, crit_p):
            alerts.append({
                'type': 'missing_backup',
                'severity': 'high',
                'due_on': d['due_on'],
                'message': f"Critical project deadline '{d['title']}' (owner: {d['owner_name']}) lacks an assigned backup!"
            })

        # 5. Timeline items (project deadlines, return to work, custom items)
        tl = list_timeline(actor, today.isoformat(), end.isoformat(), db_path=db_path)
        for r in tl:
            if r.get('status') == 'completed':
                continue
            due_dt = date.fromisoformat(r['due_on'])
            sev = 'high' if (due_dt < today or r.get('priority') in ('high', 'critical')) else 'medium' if r.get('priority') == 'normal' else 'low'
            alerts.append({
                'type': r['item_type'],
                'severity': sev,
                'due_on': r['due_on'],
                'message': f"[{r.get('priority', 'normal').upper()}] {r['title']}"
            })
    return sorted(alerts, key=lambda x: (x['due_on'], 0 if x['severity'] == 'high' else 1 if x['severity'] == 'medium' else 2))


def comp_off_summary(actor: UserContext, employee_id: Optional[str] = None,
                     as_of: Optional[Union[str, date]] = None, db_path=DB_PATH) -> Dict[str, Any]:
    from access_control.service import require_employee_scope
    target = employee_id or actor.employee_id
    require_employee_scope(actor, target, db_path)
    if isinstance(as_of, date):
        today = as_of
    elif isinstance(as_of, str):
        today = date.fromisoformat(as_of)
    else:
        today = date.today()
    with connection(db_path) as c:
        rows = [dict(r) for r in c.execute('''SELECT comp_off_id, earned_on, expires_on, days, status, used_on, work_reference
             FROM comp_off_records WHERE employee_id=? ORDER BY expires_on, comp_off_id''', (target,))]
        pending_row = c.execute(
            """SELECT COALESCE(SUM(requested_days), 0.0) FROM leave_requests
               WHERE employee_id=? AND leave_type='comp_off' AND status IN ('pending', 'needs_review')""",
            (target,)
        ).fetchone()
        pending_days = float(pending_row[0]) if pending_row else 0.0

    earned_days = round(sum(r['days'] for r in rows), 2)
    used_days = round(sum(r['days'] for r in rows if r['status'] == 'used'), 2)
    available_days = round(sum(r['days'] for r in rows if r['status'] == 'available' and r['expires_on'] >= today.isoformat()), 2)
    remaining_days = round(max(0.0, available_days - pending_days), 2)

    for r in rows:
        exp_dt = date.fromisoformat(r['expires_on'])
        days_left = (exp_dt - today).days
        r['days_to_expiry'] = days_left
        if r['status'] == 'available' and exp_dt < today:
            r['display_status'] = 'expired_pending_refresh'
            r['is_expired'] = True
            r['is_valid'] = False
            r['is_expiring_soon'] = False
        elif r['status'] == 'expired':
            r['display_status'] = 'expired'
            r['is_expired'] = True
            r['is_valid'] = False
            r['is_expiring_soon'] = False
        elif r['status'] == 'used':
            r['display_status'] = 'used'
            r['is_expired'] = False
            r['is_valid'] = False
            r['is_expiring_soon'] = False
        else: # available and unexpired
            r['display_status'] = 'available'
            r['is_expired'] = False
            r['is_valid'] = True
            r['is_expiring_soon'] = (0 <= days_left <= 14)

    expired_days = round(sum(r['days'] for r in rows if r['status'] == 'expired' or r['display_status'] == 'expired_pending_refresh'), 2)

    return {
        'employee_id': target,
        'records': rows,
        'earned_days': earned_days,
        'available_days': available_days,
        'pending_days': pending_days,
        'remaining_days': remaining_days,
        'used_days': used_days,
        'expired_days': expired_days,
    }


def query_timeline_overlap(actor: UserContext, team_id: str,
                           start_date: Union[str, date], end_date: Union[str, date],
                           employee_id: Optional[str] = None,
                           db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Analyze timeline overlaps for proposed leave dates against project deadlines and events.

    Answers questions such as:
    - Which project deadlines occur during the proposed leave span?
    - Is the requester an owner of any critical deliverables?
    - Are backups assigned and available?
    - What is the projected team coverage?
    """
    from workforce_planning.service import team_capacity_forecast, list_team_deadlines
    start_dt, end_dt = _as_date(start_date), _as_date(end_date)
    if end_dt < start_dt:
        raise ValueError("End date cannot be before start date.")

    # 1. Project deadlines in the period
    deadlines = list_team_deadlines(team_id, start_dt, end_dt, db_path=db_path)
    owned_deadlines = [d for d in deadlines if employee_id and d.get("owner_id") == employee_id]
    critical_owned = [d for d in owned_deadlines if d.get("critical")]
    critical_missing_backup = [d for d in critical_owned if not d.get("backup_employee_id")]

    # 2. Timeline items in the window
    tl_items = list_timeline(actor, start_dt.isoformat(), end_dt.isoformat(), db_path=db_path)

    # 3. Capacity forecast for the team
    forecast = team_capacity_forecast(team_id, start_dt, end_dt, db_path=db_path)
    breach_days = forecast.get("breach_dates", [])

    # 4. Formulate natural language summary explanation
    reasons = []
    if deadlines:
        reasons.append(f"{len(deadlines)} team project deadline(s) fall within the requested date span.")
    else:
        reasons.append("No team project deadlines coincide with the requested dates.")

    if critical_missing_backup:
        reasons.append(
            f"HIGH OPERATIONAL RISK: Requester owns {len(critical_missing_backup)} critical deadline(s) without an assigned backup."
        )
    elif critical_owned:
        reasons.append(
            f"Requester owns {len(critical_owned)} critical deadline(s), but backup coverage is assigned."
        )

    if breach_days:
        reasons.append(
            f"Staffing warning: Active team coverage falls below minimum threshold on {len(breach_days)} day(s)."
        )
    else:
        reasons.append("Team staffing meets or exceeds configured coverage requirements throughout the period.")

    summary_text = " ".join(reasons)

    return {
        "team_id": team_id,
        "employee_id": employee_id,
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
        "deadlines_count": len(deadlines),
        "deadlines": deadlines,
        "owned_deadlines": owned_deadlines,
        "critical_owned_deadlines": critical_owned,
        "critical_deadlines_missing_backup": critical_missing_backup,
        "timeline_items": tl_items,
        "coverage_forecast": forecast,
        "coverage_breach_dates": [d["date"] for d in breach_days],
        "has_operational_risk": len(critical_missing_backup) > 0 or len(breach_days) > 0,
        "explanation": summary_text
    }


def record_comp_off(actor: UserContext, employee_id: str, earned_on: str, expires_on: str,
                    days: float = 1.0, db_path=DB_PATH, work_reference: str = "") -> int:
    """Record manager/HR-verified comp-off entitlement for a synthetic employee."""
    require_role(actor, 'manager', 'hr')
    earned = date.fromisoformat(earned_on)
    expires = date.fromisoformat(expires_on)
    if expires < earned:
        raise ValueError('Expiry cannot be before earned date.')
    if days <= 0:
        raise ValueError('Comp-off days must be positive.')
    with connection(db_path) as c:
        emp = c.execute('SELECT team_id, is_active FROM employees WHERE employee_id=?', (employee_id,)).fetchone()
        if not emp or not emp['is_active']:
            raise ValueError('Employee not found or inactive.')
        if actor.role == 'manager' and emp['team_id'] != actor.team_id:
            raise PermissionError('Outside manager team scope.')
        cur = c.execute(
            """INSERT INTO comp_off_records(employee_id, earned_on, expires_on, days, status, work_reference)
               VALUES (?, ?, ?, ?, 'available', ?)""",
            (employee_id, earned.isoformat(), expires.isoformat(), float(days), work_reference.strip() or None)
        )
        cid = int(cur.lastrowid)
    log_audit(actor.employee_id, actor.role, "record_compoff", str(cid), f"Granted {days} day(s) comp-off to {employee_id}", db_path)
    return cid

