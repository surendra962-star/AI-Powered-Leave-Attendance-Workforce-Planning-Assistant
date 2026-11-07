"""Filterable attendance and leave analytics with explicit metric definitions."""
from __future__ import annotations
import csv
import io
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
from database.db import DB_PATH, connection
from access_control.service import UserContext, require_role
from workforce_planning.service import team_coverage, _as_date


def workforce_metrics(actor: UserContext, month: str, team_id: Optional[str] = None,
                      employee_id: Optional[str] = None, leave_type: Optional[str] = None,
                      status: Optional[str] = None, db_path=DB_PATH) -> Dict[str, Any]:
    """Calculate multi-dimensional workforce metrics with explicit definitions and leave breakdowns."""
    date.fromisoformat(month + '-01')
    if actor.role == 'employee':
        if employee_id not in (None, actor.employee_id):
            raise PermissionError('Employee scope violation.')
        employee_id = actor.employee_id
        team_id = actor.team_id
    elif actor.role == 'manager':
        require_role(actor, 'manager')
        if team_id not in (None, actor.team_id):
            raise PermissionError('Manager may view only their team.')
        team_id = actor.team_id

    with connection(db_path) as c:
        if actor.role == 'manager' and employee_id:
            emp_team = c.execute("SELECT team_id FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
            if not emp_team or emp_team['team_id'] != actor.team_id:
                raise PermissionError('Manager may only view employees within their own team.')

        where = ['substr(a.date,1,7)=?']
        params: List[Any] = [month]
        if employee_id:
            where.append('a.employee_id=?')
            params.append(employee_id)
        if team_id:
            where.append('e.team_id=?')
            params.append(team_id)
        attendance = c.execute('''SELECT COUNT(*) scheduled_days,
          SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) present_days,
          SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) absent_days,
          SUM(CASE WHEN a.status='approved_leave' THEN 1 ELSE 0 END) approved_leave_days
          FROM attendance a JOIN employees e ON e.employee_id=a.employee_id WHERE ''' + ' AND '.join(where), params).fetchone()

        lw = ['substr(lr.start_date,1,7)=?']
        lp: List[Any] = [month]
        if employee_id:
            lw.append('lr.employee_id=?')
            lp.append(employee_id)
        if team_id:
            lw.append('e.team_id=?')
            lp.append(team_id)
        if leave_type:
            lw.append('lr.leave_type=?')
            lp.append(leave_type)
        if status:
            lw.append('lr.status=?')
            lp.append(status)
        leaves = [dict(r) for r in c.execute('''SELECT lr.request_id,lr.employee_id,e.name,lr.leave_type,lr.start_date,lr.end_date,lr.requested_days,lr.status
          FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id WHERE ''' + ' AND '.join(lw) + ' ORDER BY lr.start_date', lp)]

    d = dict(attendance)
    present = int(d['present_days'] or 0)
    absent = int(d['absent_days'] or 0)
    total = int(d['scheduled_days'] or 0)
    approved_leave = int(d['approved_leave_days'] or 0)
    attendance_pct = round(present / (present + absent) * 100, 2) if (present + absent) else None

    # Granular leave-type breakdown aggregation
    leave_type_breakdown: Dict[str, Dict[str, Any]] = {
        'annual': {'requests_count': 0, 'total_days': 0.0, 'approved_days': 0.0, 'pending_days': 0.0, 'declined_days': 0.0},
        'sick': {'requests_count': 0, 'total_days': 0.0, 'approved_days': 0.0, 'pending_days': 0.0, 'declined_days': 0.0},
        'comp_off': {'requests_count': 0, 'total_days': 0.0, 'approved_days': 0.0, 'pending_days': 0.0, 'declined_days': 0.0},
    }
    total_requested_days = 0.0
    for lr in leaves:
        l_kind = lr['leave_type']
        days = float(lr['requested_days'])
        l_stat = lr['status']
        if l_kind not in leave_type_breakdown:
            leave_type_breakdown[l_kind] = {'requests_count': 0, 'total_days': 0.0, 'approved_days': 0.0, 'pending_days': 0.0, 'declined_days': 0.0}
        leave_type_breakdown[l_kind]['requests_count'] += 1
        leave_type_breakdown[l_kind]['total_days'] = round(leave_type_breakdown[l_kind]['total_days'] + days, 2)
        total_requested_days = round(total_requested_days + days, 2)
        if l_stat == 'approved':
            leave_type_breakdown[l_kind]['approved_days'] = round(leave_type_breakdown[l_kind]['approved_days'] + days, 2)
        elif l_stat in ('pending', 'needs_review'):
            leave_type_breakdown[l_kind]['pending_days'] = round(leave_type_breakdown[l_kind]['pending_days'] + days, 2)
        elif l_stat == 'declined':
            leave_type_breakdown[l_kind]['declined_days'] = round(leave_type_breakdown[l_kind]['declined_days'] + days, 2)

    return {
        'month': month,
        'attendance': {
            'scheduled_records': total,
            'present_days': present,
            'absent_days': absent,
            'approved_leave_days': approved_leave,
            'attendance_percent': attendance_pct,
            'attendance_percentage': attendance_pct
        },
        'leave_requests': leaves,
        'leave_type_breakdown': leave_type_breakdown,
        'leave_summary': {
            'total_requests': len(leaves),
            'total_requested_days': total_requested_days,
        },
        'definitions': {
            'attendance_percent': 'Formula: Present days / (Present days + Absent days) * 100. Approved leave is excluded from the denominator. Dataset reflects recorded attendance rows.',
            'attendance_percentage': 'Formula: Present days / (Present days + Absent days) * 100. Approved leave is excluded from the denominator. Dataset reflects recorded attendance rows.',
            'approved_leave_effect': 'Approved leave is authorized scheduled absence and is excluded from the attendance percentage denominator; it does not penalize the employee.',
            'holiday_and_weekend_effect': 'Non-working days (weekends and designated public holidays) are non-scheduled days and excluded from attendance logging and leave deductions.',
            'team_coverage_percentage': 'Formula: Available Active Team Members / Total Active Team Members * 100. Team members on approved or pending leave are excluded from available count.',
            'comp_off_balance': 'Formula: Earned Comp-off Days - (Used Days + Expired Days). Only available unexpired records may be applied.'
        }
    }


def get_team_coverage_analytics(actor: UserContext, team_id: str, start_date: str, end_date: str,
                                db_path=DB_PATH) -> Dict[str, Any]:
    """Calculate date-by-date active coverage, planned absences, and threshold breaches for a team."""
    if actor.role == 'employee' and actor.team_id != team_id:
        raise PermissionError('Employees may only view their assigned team coverage.')
    if actor.role == 'manager' and actor.team_id != team_id:
        raise PermissionError('Managers may only view their assigned team coverage.')

    start = _as_date(start_date)
    end = _as_date(end_date)
    if end < start:
        raise ValueError('End date cannot precede start date.')

    with connection(db_path) as conn:
        t_row = conn.execute("SELECT team_id, name, min_coverage_percent FROM teams WHERE team_id=?", (team_id,)).fetchone()
        if not t_row:
            raise ValueError(f"Unknown team: {team_id}")
        min_cov = int(t_row['min_coverage_percent'])
        team_name = t_row['name']

    daily = []
    breach_dates = []
    total_planned_absence_days = 0
    all_absences = []

    cur = start
    while cur <= end:
        cov = team_coverage(team_id, cur, db_path=db_path)
        is_working = cov['is_working_day']
        cov_pct = cov['coverage_percent']
        meets_min = cov['meets_minimum']
        absences = cov['planned_absences']

        if is_working and not meets_min:
            breach_dates.append(cur.isoformat())

        if is_working:
            total_planned_absence_days += len(absences)
            for ab in absences:
                all_absences.append({
                    'date': cur.isoformat(),
                    'employee_id': ab['employee_id'],
                    'employee_name': ab['name'],
                })

        daily.append({
            'date': cur.isoformat(),
            'is_working_day': is_working,
            'total_active_employees': cov['total_active_employees'],
            'available_count': cov['available_count'],
            'absent_count': cov['absent_count'],
            'coverage_percent': cov_pct,
            'meets_minimum': meets_min,
            'planned_absences': absences
        })
        cur += timedelta(days=1)

    working_days_cov = [d['coverage_percent'] for d in daily if d['is_working_day']]
    avg_cov = round(sum(working_days_cov) / len(working_days_cov), 2) if working_days_cov else 100.0
    lowest_cov = min(working_days_cov) if working_days_cov else 100.0

    return {
        'team_id': team_id,
        'team_name': team_name,
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'minimum_coverage_percent': min_cov,
        'average_coverage_percent': avg_cov,
        'lowest_coverage_percent': lowest_cov,
        'breach_count': len(breach_dates),
        'breach_dates': breach_dates,
        'total_planned_absence_instances': total_planned_absence_days,
        'planned_absences_log': all_absences,
        'daily_coverage': daily
    }


def organization_workforce_summary(actor: UserContext, month: Optional[str] = None, db_path=DB_PATH) -> Dict[str, Any]:
    """HR and Manager high-level organization/team workforce health metrics."""
    require_role(actor, 'hr', 'manager')
    today_str = date.today().isoformat()
    with connection(db_path) as conn:
        headcount = conn.execute("SELECT COUNT(*) FROM employees WHERE is_active=1").fetchone()[0]
        by_team = [dict(r) for r in conn.execute(
            """SELECT t.team_id, t.name as team_name, COUNT(e.employee_id) as headcount
               FROM teams t LEFT JOIN employees e ON e.team_id=t.team_id AND e.is_active=1
               GROUP BY t.team_id, t.name ORDER BY t.name"""
        ).fetchall()]
        by_role = [dict(r) for r in conn.execute(
            """SELECT role, COUNT(*) as count FROM employees WHERE is_active=1 GROUP BY role"""
        ).fetchall()]
        leave_utilization = [dict(r) for r in conn.execute(
            """SELECT leave_type, SUM(entitled_days) as total_entitled, SUM(used_days) as total_used,
                      ROUND(SUM(used_days) * 100.0 / NULLIF(SUM(entitled_days), 0), 2) as utilization_percent
               FROM leave_balances GROUP BY leave_type"""
        ).fetchall()]
        request_statuses = [dict(r) for r in conn.execute(
            """SELECT status, COUNT(*) as count FROM leave_requests GROUP BY status"""
        ).fetchall()]
        # Comp-off balance summary across the org
        comp_summary = dict(conn.execute("""
            SELECT
                COALESCE(SUM(days), 0.0) as total_earned,
                COALESCE(SUM(CASE WHEN status='available' AND expires_on >= ? THEN days ELSE 0.0 END), 0.0) as available,
                COALESCE(SUM(CASE WHEN status='used' THEN days ELSE 0.0 END), 0.0) as used,
                COALESCE(SUM(CASE WHEN status='expired' OR (status='available' AND expires_on < ?) THEN days ELSE 0.0 END), 0.0) as expired
            FROM comp_off_records
        """, (today_str, today_str)).fetchone())
    return {
        "active_employees": int(headcount),
        "by_team": by_team,
        "by_role": by_role,
        "leave_utilization": leave_utilization,
        "leave_statuses": request_statuses,
        "comp_off_summary": comp_summary,
    }


def export_metrics_csv(actor: UserContext, month: str, team_id: Optional[str] = None,
                       db_path=DB_PATH) -> str:
    """Generate a clean CSV text string for workforce analytics export."""
    metrics = workforce_metrics(actor, month, team_id=team_id, db_path=db_path)
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["WORKFORCE ANALYTICS SUMMARY", f"Month: {month}"])
    writer.writerow([])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Scheduled Records", metrics["attendance"]["scheduled_records"]])
    writer.writerow(["Present Days", metrics["attendance"]["present_days"]])
    writer.writerow(["Absent Days", metrics["attendance"]["absent_days"]])
    writer.writerow(["Approved Leave Days", metrics["attendance"]["approved_leave_days"]])
    writer.writerow(["Attendance Percentage", f"{metrics['attendance']['attendance_percent']}%" if metrics['attendance']['attendance_percent'] is not None else "N/A"])
    writer.writerow([])
    writer.writerow(["LEAVE BREAKDOWN BY TYPE"])
    writer.writerow(["Type", "Requests", "Total Days", "Approved Days", "Pending Days", "Declined Days"])
    for lt, stats in metrics.get("leave_type_breakdown", {}).items():
        writer.writerow([lt, stats["requests_count"], stats["total_days"], stats["approved_days"], stats["pending_days"], stats["declined_days"]])
    writer.writerow([])
    writer.writerow(["LEAVE REQUESTS FOR PERIOD"])
    writer.writerow(["Request ID", "Employee ID", "Employee Name", "Type", "Start Date", "End Date", "Days", "Status"])
    for lr in metrics["leave_requests"]:
        writer.writerow([lr["request_id"], lr["employee_id"], lr["name"], lr["leave_type"], lr["start_date"], lr["end_date"], lr["requested_days"], lr["status"]])

    return output.getvalue()


