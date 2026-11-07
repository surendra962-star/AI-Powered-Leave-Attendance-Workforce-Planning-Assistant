"""Streamlit UI for the AI-Powered Leave, Attendance & Workforce Planning Assistant."""
from datetime import date, timedelta
import io
import streamlit as st
import pandas as pd

from access_control.service import (
    authenticate, AccessError, initialize_security, set_employee_password,
    create_employee, deactivate_employee, list_all_employees, get_audit_logs, UserContext
)
from database.db import initialize, connection, DB_PATH
from database.seed import seed
from leave_management.service import (
    create_leave_request, decide_leave_request, cancel_leave_request,
    get_balance, list_holidays, refresh_comp_off_status, working_days,
    list_leave_requests, get_optional_holidays_in_range,
    get_calendar_breakdown, explain_leave_interaction, LeaveError
)
from dashboards.service import employee_dashboard, manager_dashboard, hr_dashboard, get_decision_history
from workforce_planning.service import (
    evaluate_leave_request, team_coverage, recommend_backups, team_capacity_forecast,
    simulate_what_if_leave
)
from timeline.service import (
    get_alerts, list_timeline, add_timeline_item, comp_off_summary, record_comp_off,
    query_timeline_overlap, calculate_return_to_work_date
)
from attendance.service import (
    clock_in, clock_out, get_employee_attendance, get_team_attendance,
    get_hr_attendance_overview, get_monthly_attendance_summary, export_attendance_csv,
    get_missing_clock_outs, regularize_missing_clock_out, AttendanceError
)
from analytics.service import workforce_metrics, organization_workforce_summary, export_metrics_csv, get_team_coverage_analytics
from api_client import FlaskAPIClient

st.set_page_config(
    page_title="AI HR Assistant",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database schema and security
try:
    initialize()
    initialize_security()
except Exception:
    pass

st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 12px;
        border-left: 4px solid #1f77b4;
    }
    .badge-approved { color: #28a745; font-weight: bold; }
    .badge-pending { color: #ffc107; font-weight: bold; }
    .badge-declined { color: #dc3545; font-weight: bold; }
    .stAlert { border-radius: 6px; }
</style>
""", unsafe_allow_html=True)

# Top Header
st.title("🏢 AI-Powered Leave, Attendance & Workforce Planning Assistant")
st.caption("Policy-Grounded RAG · Deterministic Business Rules · Explainable Workforce Planning · Human Decision Authority")

# Authentication Handler
if "actor" not in st.session_state:
    st.markdown("---")
    col1, col2 = st.columns([1.2, 1])

    with col1:
        st.subheader("🔐 Sign in to Workspace")
        with st.form("login_form"):
            uid = st.text_input("Employee ID", placeholder="e.g. HR001, E005, E001")
            pwd = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            if not uid.strip() or not pwd:
                st.error("Please enter both Employee ID and password.")
            else:
                try:
                    st.session_state.actor = authenticate(uid.strip(), pwd)
                    st.success(f"Welcome back, {st.session_state.actor.name}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Authentication failed: {e}")

    with col2:
        st.info("💡 **Demo Assessment Accounts & Credentials**\n\n"
                "You can log in with any of these pre-seeded demo accounts:\n\n"
                "- **HR Administrator**: `HR001` / `hradmin@2026`\n"
                "- **Engineering Manager**: `E005` / `kiranmgr@2026` (Team T01)\n"
                "- **Senior Employee**: `E001` / `rahuluser@2026` (Team T01)\n"
                "- **Product Manager**: `E010` / `vikrammgr@2026` (Team T02)\n"
                "- **Analyst Employee**: `E006` / `raviuser@2026` (Team T02)\n\n"
                "*All credentials use salted SHA-256 hashes stored in SQLite.*")

        with st.expander("🛠️ Database Tools (Reset / Seed)"):
            if st.button("Re-seed Synthetic Database"):
                try:
                    seed()
                    st.success("Database re-seeded successfully with 11 employees, policies, and demo credentials.")
                except Exception as ex:
                    st.error(f"Seeding failed: {ex}")
    st.stop()

actor: UserContext = st.session_state.actor

# Sidebar Navigation
with st.sidebar:
    st.markdown(f"### 👤 {actor.name}")
    st.markdown(f"**Role:** `{actor.role.upper()}` | **ID:** `{actor.employee_id}`")
    st.caption(f"Team: {actor.team_id}")
    st.markdown("---")

    nav_pages = [
        "My Dashboard",
        "Apply for Leave",
        "Attendance Management",
        "Comp-off & Holidays",
        "Timeline & Alerts",
        "Workforce Analytics",
        "HR Policy Assistant (RAG)"
    ]
    if actor.role in ("manager", "hr"):
        nav_pages += ["Manager Review & Coverage"]
    if actor.role == "hr":
        nav_pages += ["HR Employee Admin", "System Audit Logs"]

    page = st.radio("Navigation", nav_pages)

    st.markdown("---")
    api_client = FlaskAPIClient()
    flask_connected = api_client.is_healthy()
    if flask_connected:
        st.success("🟢 Flask REST API: Connected (`:5000`)")
    else:
        st.info("🟡 Backend: Direct Python Service Mode")

    if st.button("🚪 Sign Out", use_container_width=True):
        del st.session_state.actor
        st.rerun()

# Global Alerts Banner (Next 30 Days)
try:
    active_alerts = get_alerts(actor, horizon_days=30)
    if active_alerts:
        with st.expander(f"🔔 Active Alerts & Deadlines ({len(active_alerts)} upcoming in 30 days)", expanded=False):
            st.dataframe(pd.DataFrame(active_alerts), use_container_width=True, hide_index=True)
except Exception as e:
    st.caption(f"Alert service notification: {e}")

# ==============================================================================
# 1. MY DASHBOARD
# ==============================================================================
if page == "My Dashboard":
    st.header("📋 Employee Personal Dashboard")
    try:
        data = employee_dashboard(actor)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Attendance Days", data["attendance"]["total"])
        c2.metric("Present Days", data["attendance"]["present"])
        c3.metric("Absences / Leaves", data["attendance"]["not_present"])

        comp_summary = comp_off_summary(actor, employee_id=actor.employee_id)
        c4.metric("Available Comp-off Days", comp_summary["available_days"])

        st.subheader("🏖️ Leave Balances (Year 2026)")
        if data["balances"]:
            st.dataframe(pd.DataFrame(data["balances"]), use_container_width=True, hide_index=True)
        else:
            st.info("No leave balances assigned.")

        st.subheader("📄 My Leave Request History")
        if data["leave_requests"]:
            df_requests = pd.DataFrame(data["leave_requests"])
            st.dataframe(df_requests, use_container_width=True, hide_index=True)

            # Option to cancel pending or approved leaves
            with st.expander("Cancel an Active or Pending Leave Request"):
                active_reqs = [r for r in data["leave_requests"] if r["status"] in ("pending", "needs_review", "approved")]
                if active_reqs:
                    cancel_id = st.selectbox("Select Leave Request to Cancel",
                                             [f"#{r['request_id']} | {r['leave_type']} ({r['start_date']} to {r['end_date']}) - {r['status']}" for r in active_reqs])
                    c_reason = st.text_input("Cancellation Reason", placeholder="Change of plans")
                    if st.button("Cancel Leave Request"):
                        req_num = int(cancel_id.split(" | ")[0].replace("#", ""))
                        try:
                            res = cancel_leave_request(actor, req_num, reason=c_reason)
                            st.success(f"Leave request #{req_num} cancelled. Balances restored.")
                            st.rerun()
                        except Exception as ce:
                            st.error(str(ce))
                else:
                    st.write("No active or pending requests eligible for cancellation.")
        else:
            st.info("No leave requests found.")
    except Exception as ex:
        st.error(f"Error loading dashboard: {ex}")

# ==============================================================================
# 2. APPLY FOR LEAVE
# ==============================================================================
elif page == "Apply for Leave":
    st.header("📝 Submit Leave Request")
    st.write("Submit a request for deterministic business rule validation and manager review.")

    with st.form("leave_form"):
        l_col1, l_col2 = st.columns(2)
        leave_type = l_col1.selectbox("Leave Type", ["annual", "sick", "comp_off"])
        reason = l_col2.text_input("Reason / Justification", placeholder="e.g. Family vacation, medical appointment")

        d_col1, d_col2 = st.columns(2)
        start_dt = d_col1.date_input("Start Date", date.today() + timedelta(days=7))
        end_dt = d_col2.date_input("End Date", date.today() + timedelta(days=7))

        exclude_opt = False
        if end_dt >= start_dt:
            opt_hols = get_optional_holidays_in_range(start_dt, end_dt)
            if opt_hols:
                names = ", ".join(f"{h['name']} ({h['date']})" for h in opt_hols)
                exclude_opt = st.checkbox(f"🎉 Elect to claim optional holiday: {names} (excludes from chargeable leave days)")

        submit_btn = st.form_submit_button("Submit Leave Request", use_container_width=True)

    # Real-time calculation helper
    if end_dt >= start_dt:
        try:
            w_days = working_days(start_dt, end_dt, exclude_optional_holidays=exclude_opt)
            st.info(f"📅 **Duration Preview**: {w_days} working day(s) calculated (excluding weekends & designated holidays).")
            if leave_type == "annual":
                notice_days = (start_dt - date.today()).days
                if notice_days < 5:
                    st.warning(f"⚠️ Annual leave policy requires at least 5 calendar days advance notice. (Current notice: {notice_days} days).")

            with st.expander("💡 Holiday, Working Day & Comp-off Interaction Breakdown", expanded=False):
                explanation = explain_leave_interaction(
                    leave_type=leave_type,
                    start_date=start_dt,
                    end_date=end_dt,
                    employee_id=actor.employee_id,
                    exclude_optional_holidays=exclude_opt
                )
                st.markdown(f"**Policy Summary**: {explanation['explanation_summary']}")
                if explanation["calendar_breakdown"]:
                    st.dataframe(pd.DataFrame(explanation["calendar_breakdown"]), use_container_width=True, hide_index=True)
        except Exception:
            pass

    if submit_btn:
        try:
            if flask_connected:
                req_id = api_client.submit_leave_request(
                    actor=actor,
                    leave_type=leave_type,
                    start_date=start_dt.isoformat(),
                    end_date=end_dt.isoformat(),
                    reason=reason,
                    exclude_optional_holidays=exclude_opt
                )
            else:
                req_id = create_leave_request(
                    employee_id=actor.employee_id,
                    leave_type=leave_type,
                    start_date=start_dt.isoformat(),
                    end_date=end_dt.isoformat(),
                    reason=reason,
                    submitted_on=date.today().isoformat(),
                    exclude_optional_holidays=exclude_opt
                )
            backend_lbl = "via Flask REST API (`POST /api/leave/request`)" if flask_connected else "via Direct Service"
            st.success(f"✅ Leave request #{req_id} successfully created and submitted {backend_lbl} for manager review. "
                       f"Please note: autonomous AI approval is disabled; your manager retains final decision authority.")
        except Exception as ex:
            st.error(f"Validation Error: {ex}")

# ==============================================================================
# 3. ATTENDANCE MANAGEMENT
# ==============================================================================
elif page == "Attendance Management":
    st.header("⏱️ Attendance Management & Daily Tracking")

    att_tab1, att_tab2 = st.tabs(["Daily Check-in / History", "Team & Org Attendance"])

    with att_tab1:
        st.subheader("Daily Clock-In / Clock-Out")
        today_str = date.today().isoformat()
        t_col1, t_col2 = st.columns(2)

        if t_col1.button("🕒 Clock In Today", use_container_width=True):
            try:
                res = api_client.clock_in(actor) if flask_connected else clock_in(actor, actor.employee_id)
                via_str = " (via Flask REST API)" if flask_connected else ""
                st.success(f"Clocked in at {res['check_in']} for {res['date']}{via_str}")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        if t_col2.button("🛑 Clock Out Today", use_container_width=True):
            try:
                res = api_client.clock_out(actor) if flask_connected else clock_out(actor, actor.employee_id)
                via_str = " (via Flask REST API)" if flask_connected else ""
                st.success(f"Clocked out at {res['check_out']} for {res['date']}{via_str}")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        st.markdown("---")
        st.subheader("My Monthly Attendance Summary")
        month_sel = st.text_input("Month (YYYY-MM)", date.today().strftime("%Y-%m"))
        try:
            summary = get_monthly_attendance_summary(actor, month_sel, employee_id=actor.employee_id)
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Present Days", summary["present_days"])
            sc2.metric("Absent Days", summary["absent_days"])
            sc3.metric("Approved Leave", summary["approved_leave_days"])
            sc4.metric("Attendance %", f"{summary['attendance_percentage']}%" if summary["attendance_percentage"] is not None else "N/A")
            st.caption(summary["calculation_note"])
        except Exception as ex:
            st.warning(f"Could not calculate summary: {ex}")

        st.subheader("Personal Attendance Log")
        history = get_employee_attendance(actor, actor.employee_id)
        if history:
            st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
        else:
            st.info("No attendance records logged yet.")

    with att_tab2:
        if actor.role in ("manager", "hr"):
            st.subheader("Team & Organization Daily Attendance")
            inspect_date = st.date_input("Select Inspection Date", date.today())
            try:
                team_records = get_team_attendance(actor, target_date=inspect_date.isoformat())
                if team_records:
                    st.write(f"Attendance for Team `{actor.team_id}` on `{inspect_date.isoformat()}`:")
                    st.dataframe(pd.DataFrame(team_records), use_container_width=True, hide_index=True)
                else:
                    st.info("No team records found.")
            except Exception as e:
                st.error(str(e))

            st.markdown("---")
            st.subheader("⚠️ Missing Clock-Outs & Regularization")
            st.caption("Identify records where employees clocked in but never completed clock-out.")
            missing_outs = get_missing_clock_outs(actor)
            if missing_outs:
                st.warning(f"Found {len(missing_outs)} incomplete attendance record(s) with missing clock-outs:")
                st.dataframe(pd.DataFrame(missing_outs), use_container_width=True, hide_index=True)

                with st.expander("🛠️ Regularize a Missing Clock-Out", expanded=False):
                    reg_options = [f"{m['employee_id']} on {m['date']} (Check-in: {m['check_in']})" for m in missing_outs]
                    reg_pick = st.selectbox("Select Record to Regularize", reg_options)
                    reg_emp = reg_pick.split(" on ")[0]
                    reg_date = reg_pick.split(" on ")[1].split(" (")[0]
                    reg_time = st.text_input("Default End Time", "17:00:00")
                    reg_note = st.text_input("Regularization Note", "Manager-approved attendance regularization")
                    if st.button("Apply Regularization", key="apply_reg"):
                        try:
                            reg_res = regularize_missing_clock_out(actor, reg_emp, reg_date, default_check_out=reg_time, note=reg_note)
                            st.success(f"Regularized {reg_res['employee_id']} on {reg_res['date']} with check-out {reg_res['check_out']}.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))
            else:
                st.success("✅ No incomplete records with missing clock-outs found.")

            if actor.role == "hr":
                st.markdown("---")
                st.subheader("Organization-wide Daily Overview (HR)")
                try:
                    hr_ov = get_hr_attendance_overview(actor, target_date=inspect_date.isoformat())
                    oc1, oc2, oc3, oc4 = st.columns(4)
                    oc1.metric("Total Active", hr_ov["total_active_employees"])
                    oc2.metric("Present", hr_ov["present_count"])
                    oc3.metric("Absent", hr_ov["absent_count"])
                    oc4.metric("Approved Leave", hr_ov["approved_leave_count"])
                    st.dataframe(pd.DataFrame(hr_ov["records"]), use_container_width=True, hide_index=True)

                    st.markdown("### Export Attendance Records")
                    csv_data = export_attendance_csv(actor)
                    st.download_button(
                        label="📥 Download Full Attendance CSV",
                        data=csv_data,
                        file_name=f"attendance_export_{date.today().isoformat()}.csv",
                        mime="text/csv"
                    )
                except Exception as ex:
                    st.error(str(ex))
        else:
            st.info("Team and organization attendance views require Manager or HR role.")

# ==============================================================================
# 4. COMP-OFF & HOLIDAYS
# ==============================================================================
elif page == "Comp-off & Holidays":
    st.header("🎁 Compensatory Off & Public Holidays")

    target_emp = actor.employee_id
    if actor.role in ("manager", "hr"):
        st.subheader("Comp-off Balances by Employee")
        with connection() as conn:
            if actor.role == "hr":
                cand_list = [dict(r) for r in conn.execute("SELECT employee_id, name FROM employees WHERE is_active=1 ORDER BY name")]
            else:
                cand_list = [dict(r) for r in conn.execute("SELECT employee_id, name FROM employees WHERE is_active=1 AND team_id=? ORDER BY name", (actor.team_id,))]
        cand_pick = st.selectbox("Inspect Employee", [f"{x['employee_id']} — {x['name']}" for x in cand_list])
        target_emp = cand_pick.split(" — ")[0]

    c_summary = comp_off_summary(actor, employee_id=target_emp)
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Available Balance (Days)", c_summary["available_days"])
    cc2.metric("Used Days", c_summary["used_days"])
    cc3.metric("Expired Days", c_summary["expired_days"])

    if c_summary["records"]:
        st.dataframe(pd.DataFrame(c_summary["records"]), use_container_width=True, hide_index=True)
    else:
        st.info("No comp-off grants on record for this employee.")

    if actor.role in ("manager", "hr"):
        st.markdown("---")
        st.subheader("Grant New Comp-off Entitlement")
        with st.form("grant_compoff"):
            gc_emp = st.selectbox("Grant To", [f"{x['employee_id']} — {x['name']}" for x in cand_list])
            g_earned = st.date_input("Earned On (Weekend / Overtime Work)", date.today())
            g_expires = st.date_input("Expires On", date.today() + timedelta(days=90))
            g_days = st.number_input("Entitlement Days", min_value=0.5, max_value=5.0, value=1.0, step=0.5)
            g_ref = st.text_input("Work Reference / Project", placeholder="e.g. Production sprint release deployment")
            save_comp = st.form_submit_button("Grant Comp-off")

        if save_comp:
            try:
                emp_to_grant = gc_emp.split(" — ")[0]
                cid = record_comp_off(actor, emp_to_grant, g_earned.isoformat(), g_expires.isoformat(),
                                      days=g_days, work_reference=g_ref)
                st.success(f"Comp-off grant #{cid} saved for {emp_to_grant} ({g_days} days).")
                st.rerun()
            except Exception as ex:
                st.error(str(ex))

    st.markdown("---")
    st.subheader("📅 Official Holiday Calendar & Working Day Breakdown")
    h_start = st.date_input("Holidays From", date.today())
    h_end = st.date_input("Holidays To", date.today() + timedelta(days=120))
    if h_end >= h_start:
        h_tab1, h_tab2 = st.tabs(["Official Holidays List", "Day-by-Day Calendar Breakdown"])
        with h_tab1:
            hols = list_holidays(h_start, h_end)
            if hols:
                st.dataframe(pd.DataFrame(hols), use_container_width=True, hide_index=True)
            else:
                st.info("No public or optional holidays scheduled in this range.")
        with h_tab2:
            try:
                cal_breakdown = get_calendar_breakdown(h_start, h_end)
                st.dataframe(pd.DataFrame(cal_breakdown), use_container_width=True, hide_index=True)
            except Exception as ex:
                st.warning(f"Could not load calendar breakdown: {ex}")

# ==============================================================================
# 5. TIMELINE & ALERTS
# ==============================================================================
elif page == "Timeline & Alerts":
    st.header("📆 Milestones, Deadlines & Timeline Items")

    tl_col1, tl_col2 = st.columns(2)
    tl_start = tl_col1.date_input("Filter Range From", date.today() - timedelta(days=7))
    tl_end = tl_col2.date_input("Filter Range To", date.today() + timedelta(days=60))

    if tl_end >= tl_start:
        items = list_timeline(actor, tl_start.isoformat(), tl_end.isoformat())
        if items:
            st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
        else:
            st.info("No timeline events scheduled in this date window.")

    st.markdown("---")
    st.subheader("🔍 Structured Timeline & Expiry Inquiries")
    st.caption("Ask timeline questions evaluated deterministically against persisted records (no LLM hallucination).")
    
    inq_choice = st.selectbox(
        "Select Timeline Inquiry",
        [
            "Which comp-off days expire in the next 30 days?",
            "Which comp-off days expire in the next 60 days?",
            "What project deadlines overlap with my upcoming leave?",
            "Check proposed leave dates for deadline collisions & coverage risks",
            "Which leave requests have passed their approval due date?"
        ]
    )
    
    if inq_choice.startswith("Which comp-off days expire"):
        horizon = 30 if "30" in inq_choice else 60
        summary = comp_off_summary(actor, actor.employee_id)
        expiring = [
            r for r in summary["records"]
            if r["status"] == "available" and date.today() <= date.fromisoformat(r["expires_on"]) <= date.today() + timedelta(days=horizon)
        ]
        if expiring:
            st.warning(f"Found {len(expiring)} comp-off record(s) expiring within {horizon} days:")
            st.dataframe(pd.DataFrame(expiring), use_container_width=True, hide_index=True)
        else:
            st.success(f"No comp-off days are expiring in the next {horizon} days.")
            
    elif inq_choice == "What project deadlines overlap with my upcoming leave?":
        with connection() as conn:
            user_leaves = conn.execute(
                "SELECT request_id, leave_type, start_date, end_date FROM leave_requests WHERE employee_id=? AND status IN ('pending', 'approved')",
                (actor.employee_id,)
            ).fetchall()
            if not user_leaves:
                st.info("You have no pending or approved upcoming leaves.")
            else:
                overlapping = []
                for lv in user_leaves:
                    dls = conn.execute(
                        "SELECT deadline_id, title, due_on, critical FROM project_deadlines WHERE team_id=? AND due_on BETWEEN ? AND ?",
                        (actor.team_id or "T01", lv["start_date"], lv["end_date"])
                    ).fetchall()
                    for d in dls:
                        overlapping.append({
                            "leave_request_id": lv["request_id"],
                            "leave_window": f"{lv['start_date']} to {lv['end_date']}",
                            "deadline_id": d["deadline_id"],
                            "deadline_title": d["title"],
                            "due_on": d["due_on"],
                            "critical": bool(d["critical"])
                        })
                if overlapping:
                    st.error(f"⚠️ Found {len(overlapping)} project deadline(s) overlapping your leave:")
                    st.dataframe(pd.DataFrame(overlapping), use_container_width=True, hide_index=True)
                else:
                    st.success("✅ No project deadlines overlap with your planned leave.")

    elif inq_choice == "Check proposed leave dates for deadline collisions & coverage risks":
        col_q1, col_q2 = st.columns(2)
        q_start = col_q1.date_input("Proposed Start Date", date.today() + timedelta(days=7), key="q_start")
        q_end = col_q2.date_input("Proposed End Date", date.today() + timedelta(days=11), key="q_end")
        if q_end >= q_start:
            overlap_res = query_timeline_overlap(actor, actor.team_id or "T01", q_start, q_end, employee_id=actor.employee_id)
            if overlap_res["has_operational_risk"]:
                st.error(f"⚠️ **Risk Alert**: {overlap_res['explanation']}")
            else:
                st.success(f"✅ **Feasibility Check**: {overlap_res['explanation']}")

            if overlap_res["deadlines"]:
                st.markdown("**Overlapping Team Project Deadlines:**")
                st.dataframe(pd.DataFrame(overlap_res["deadlines"]), use_container_width=True, hide_index=True)
            if overlap_res["timeline_items"]:
                st.markdown("**Scheduled Timeline Items in Window:**")
                st.dataframe(pd.DataFrame(overlap_res["timeline_items"]), use_container_width=True, hide_index=True)

    elif inq_choice == "Which leave requests have passed their approval due date?":
        with connection() as conn:
            overdue = conn.execute(
                """SELECT lr.request_id, lr.employee_id, e.name, lr.start_date, lr.end_date, lr.approval_due_on
                   FROM leave_requests lr JOIN employees e ON e.employee_id=lr.employee_id
                   WHERE lr.status IN ('pending', 'needs_review') AND lr.approval_due_on < ?""",
                (date.today().isoformat(),)
            ).fetchall()
        if overdue:
            st.error(f"Found {len(overdue)} pending leave request(s) past their approval due date:")
            st.dataframe(pd.DataFrame([dict(r) for r in overdue]), use_container_width=True, hide_index=True)
        else:
            st.success("✅ No pending leave requests are overdue for approval.")

    if actor.role in ("manager", "hr"):
        st.markdown("---")
        st.subheader("➕ Create Timeline Item")
        with st.form("add_tl_form"):
            t_title = st.text_input("Item Title", placeholder="e.g. Q4 Sprint Architecture Freeze")
            t_due = st.date_input("Due Date", date.today() + timedelta(days=14))
            t_type = st.selectbox("Category", ["project_deadline", "approval_deadline", "return_to_work", "notice_deadline", "other"])
            t_priority = st.selectbox("Priority", ["low", "normal", "high", "critical"])
            t_remind = st.date_input("Reminder Date", date.today() + timedelta(days=7))
            t_details = st.text_area("Details", placeholder="Key deliverables, required attendees, dependencies")
            save_tl = st.form_submit_button("Add Timeline Item")

        if save_tl:
            try:
                add_timeline_item(
                    actor,
                    title=t_title,
                    due_on=t_due.isoformat(),
                    item_type=t_type,
                    team_id=actor.team_id,
                    details=t_details,
                    priority=t_priority,
                    reminder_date=t_remind.isoformat()
                )
                st.success("Timeline milestone added successfully.")
                st.rerun()
            except Exception as ex:
                st.error(str(ex))

# ==============================================================================
# 6. WORKFORCE ANALYTICS
# ==============================================================================
elif page == "Workforce Analytics":
    st.header("📊 Workforce Analytics & Metrics")
    st.caption("Filterable workforce intelligence across attendance, leaves, comp-off, and coverage with explicit mathematical definitions.")

    # Multi-dimensional Filters
    st.subheader("🔍 Filters")
    f_c1, f_c2, f_c3, f_c4, f_c5 = st.columns(5)
    month_input = f_c1.text_input("Month (YYYY-MM)", date.today().strftime("%Y-%m"))

    team_filter = None
    if actor.role == "hr":
        with connection() as conn:
            teams = [dict(r) for r in conn.execute("SELECT team_id, name FROM teams ORDER BY name")]
        t_choice = f_c2.selectbox("Filter Team", ["All Teams"] + [f"{x['team_id']} — {x['name']}" for x in teams])
        if t_choice != "All Teams":
            team_filter = t_choice.split(" — ")[0]
    elif actor.role == "manager":
        f_c2.text_input("Team (Assigned)", value=actor.team_id or "T01", disabled=True)
        team_filter = actor.team_id

    # Employee Filter
    emp_filter = None
    with connection() as conn:
        emp_sql = "SELECT employee_id, name FROM employees WHERE is_active=1"
        emp_params = []
        if actor.role == "employee":
            emp_sql += " AND employee_id=?"
            emp_params.append(actor.employee_id)
        elif actor.role == "manager":
            emp_sql += " AND team_id=?"
            emp_params.append(actor.team_id)
        elif team_filter:
            emp_sql += " AND team_id=?"
            emp_params.append(team_filter)
        emp_sql += " ORDER BY name"
        cand_emps = [dict(r) for r in conn.execute(emp_sql, emp_params).fetchall()]

    if actor.role in ("manager", "hr"):
        emp_choice = f_c3.selectbox("Filter Employee", ["All Employees"] + [f"{e['employee_id']} — {e['name']}" for e in cand_emps])
        if emp_choice != "All Employees":
            emp_filter = emp_choice.split(" — ")[0]
    else:
        f_c3.text_input("Employee", value=f"{actor.employee_id} — {actor.name}", disabled=True)
        emp_filter = actor.employee_id

    lt_choice = f_c4.selectbox("Leave Type", ["All Types", "annual", "sick", "comp_off"])
    leave_type_filter = None if lt_choice == "All Types" else lt_choice

    st_choice = f_c5.selectbox("Status", ["All Statuses", "pending", "approved", "declined", "needs_review"])
    status_filter = None if st_choice == "All Statuses" else st_choice

    try:
        metrics = workforce_metrics(
            actor,
            month=month_input,
            team_id=team_filter,
            employee_id=emp_filter,
            leave_type=leave_type_filter,
            status=status_filter
        )

        st.markdown("### 📈 Monthly Attendance & Working Day Percentage")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Scheduled Attendance Rows", metrics["attendance"]["scheduled_records"])
        k2.metric("Present Days", metrics["attendance"]["present_days"])
        k3.metric("Absent Days", metrics["attendance"]["absent_days"])
        k4.metric("Approved Leave Days", metrics["attendance"]["approved_leave_days"])

        att_pct = metrics["attendance"]["attendance_percent"]
        st.metric(
            "Overall Attendance Percentage",
            f"{att_pct}%" if att_pct is not None else "N/A",
            help="Present / (Present + Absent) * 100"
        )

        with st.expander("📐 Mathematical Metric Definitions & Working-Day Rules", expanded=True):
            st.markdown(f"""
            - **Attendance Percentage Formula**: `{metrics['definitions']['attendance_percent']}`
            - **Approved Leave Effect**: {metrics['definitions']['approved_leave_effect']}
            - **Holidays & Weekends Effect**: {metrics['definitions']['holiday_and_weekend_effect']}
            - **Team Coverage Percentage Formula**: `{metrics['definitions']['team_coverage_percentage']}`
            - **Comp-off Balance Formula**: `{metrics['definitions']['comp_off_balance']}`
            """)

        # Leave Type Breakdown
        st.markdown("### 🏖️ Leave Days & Leave-Type Breakdown")
        lt_breakdown = metrics.get("leave_type_breakdown", {})
        if lt_breakdown:
            lt_rows = []
            for l_type, stats in lt_breakdown.items():
                lt_rows.append({
                    "Leave Type": l_type.replace("_", " ").title(),
                    "Total Requests": stats["requests_count"],
                    "Total Days": stats["total_days"],
                    "Approved Days": stats["approved_days"],
                    "Pending Days": stats["pending_days"],
                    "Declined Days": stats["declined_days"],
                })
            st.dataframe(pd.DataFrame(lt_rows), use_container_width=True, hide_index=True)

        st.markdown("### 📋 Filtered Leave Requests Log")
        if metrics["leave_requests"]:
            df_l = pd.DataFrame(metrics["leave_requests"])
            st.dataframe(df_l, use_container_width=True, hide_index=True)
        else:
            st.info("No leave requests matched the selected filters for this period.")

        # Team Coverage Analytics Tab
        if actor.role in ("manager", "hr"):
            st.markdown("---")
            st.subheader("👥 Team Planned Absence & Active Coverage Range Analyzer")
            target_t = team_filter or actor.team_id or "T01"
            cov_c1, cov_c2 = st.columns(2)
            c_start = cov_c1.date_input("Coverage Start Date", date.today())
            c_end = cov_c2.date_input("Coverage End Date", date.today() + timedelta(days=21))

            if c_end >= c_start:
                try:
                    t_cov_analytics = get_team_coverage_analytics(actor, target_t, c_start.isoformat(), c_end.isoformat())
                    tc1, tc2, tc3, tc4 = st.columns(4)
                    tc1.metric("Average Coverage %", f"{t_cov_analytics['average_coverage_percent']}%")
                    tc2.metric("Lowest Coverage %", f"{t_cov_analytics['lowest_coverage_percent']}%")
                    tc3.metric("Threshold Breaches", f"{t_cov_analytics['breach_count']} day(s)")
                    tc4.metric("Planned Absence Instances", t_cov_analytics["total_planned_absence_instances"])

                    if t_cov_analytics["breach_dates"]:
                        st.error(f"⚠️ Coverage dropped below required {t_cov_analytics['minimum_coverage_percent']}% on: {', '.join(t_cov_analytics['breach_dates'])}")

                    with st.expander("📅 Day-by-Day Team Coverage & Planned Absences Breakdown"):
                        daily_df = pd.DataFrame([{
                            "Date": d["date"],
                            "Working Day": "✅" if d["is_working_day"] else "No (Weekend/Holiday)",
                            "Total Active": d["total_active_employees"],
                            "Available": d["available_count"],
                            "Absent (Leave)": d["absent_count"],
                            "Coverage %": d["coverage_percent"],
                            "Meets Minimum": "✅" if d["meets_minimum"] else "❌ BREACH",
                            "Planned Absences": ", ".join(f"{x['name']} ({x['employee_id']})" for x in d["planned_absences"]) if d["planned_absences"] else "None"
                        } for d in t_cov_analytics["daily_coverage"]])
                        st.dataframe(daily_df, use_container_width=True, hide_index=True)
                except Exception as c_err:
                    st.warning(f"Could not load team coverage analytics: {c_err}")

        if actor.role == "hr":
            st.markdown("---")
            st.subheader("Organization-wide Metrics Export")
            csv_metrics = export_metrics_csv(actor, month=month_input, team_id=team_filter)
            st.download_button(
                label="📥 Export Workforce Metrics CSV",
                data=csv_metrics,
                file_name=f"workforce_metrics_{month_input}.csv",
                mime="text/csv"
            )
    except Exception as ex:
        st.error(f"Error computing analytics: {ex}")


# ==============================================================================
# 7. HR POLICY ASSISTANT (RAG)
# ==============================================================================
elif page == "HR Policy Assistant (RAG)":
    st.header("🤖 HR Policy Question Answering (RAG Assistant)")
    st.write("Answers are generated strictly from indexed company policy documents using local ChromaDB and Ollama LLM. "
             "Every response includes verifiable citations, sections, and policy versions.")

    st.markdown("""
    <div style="background-color: #f0f4f8; padding: 10px 14px; border-radius: 6px; font-size: 0.85rem; margin-bottom: 1rem; border-left: 4px solid #1f77b4;">
    <strong>Architecture Stack:</strong> Frontend: <code>Streamlit</code> | Backend: <code>Flask (REST API) / Python</code> | Relational DB: <code>SQLite</code> | Vector DB: <code>ChromaDB</code> | Embeddings: <code>Sentence Transformers</code> | LLM: <code>Ollama – Llama 3.2</code>
    </div>
    """, unsafe_allow_html=True)

    rag_col1, rag_col2 = st.columns([2, 1])
    with rag_col1:
        sample_questions = [
            "-- Select an example question or type below --",
            "How many annual leave days are provided per year?",
            "What is the sick leave eligibility and notice requirement?",
            "How much advance notice is required for annual leave?",
            "Can an employee carry forward unused leave to the next year?",
            "What is the comp-off expiry period?",
            "Which policy version applies on a given date?",
            "What happens if two policy documents contain conflicting rules?",
            "What is the reimbursement policy for interstellar spaceship travel? (Abstention Test)"
        ]
        picked_q = st.selectbox("Example Assessment Questions", sample_questions)
        custom_q = st.text_area("Your Policy Question", value="" if picked_q.startswith("--") else picked_q)

    with rag_col2:
        # Check Ollama connection status
        ollama_online = False
        ollama_models = []
        try:
            import ollama
            model_info = ollama.list()
            ollama_models = [m.model for m in model_info.models]
            ollama_online = True
        except Exception:
            pass

        available_choices = ["llama3.2", "deepseek-r1", "llama3.1", "custom"]
        model_choice = st.selectbox("LLM Model (Ollama)", available_choices)
        if model_choice == "custom":
            active_llm = st.text_input("Custom Ollama Model Name", value="llama3.2")
        else:
            active_llm = model_choice

        as_of_dt = st.date_input("Policy As-Of Date", date.today())
        
        if ollama_online:
            st.success(f"🟢 Ollama Service: Online (`{active_llm}`)")
        else:
            st.warning("⚠️ Ollama Service: Offline (Run `ollama serve` or open Ollama app)")

    with st.expander("📑 Policy Version Registry & Effective Dates (v1.0 vs v2.0 Comparison)"):
        with connection() as conn:
            pol_rows = [dict(r) for r in conn.execute(
                "SELECT policy_id, title, version, effective_from, effective_to, is_active FROM policy_documents ORDER BY effective_from"
            )]
        if pol_rows:
            st.dataframe(pd.DataFrame(pol_rows), use_container_width=True, hide_index=True)
            st.info("💡 **Effective Date Logic**: v1.0 covers 2025 (15 days annual leave, 8 days sick leave). v2.0 covers 2026 onwards (18 days annual leave, 10 days sick leave, 90-day comp-off expiry). Queries are resolved against the policy active on the specified As-Of date.")

    with st.expander("🛠️ Policy Vector Index Management (ChromaDB)"):
        st.write("If policy files were added or modified, rebuild the vector index below.")
        if st.button("🔄 Rebuild Policy Vector Index"):
            with st.spinner("Rebuilding policy chunks and ChromaDB vector embeddings..."):
                try:
                    from rag.policies import load_policies
                    from rag.chunks import split_policy
                    from rag.store import rebuild
                    pols = load_policies()
                    all_chunks = [c for p in pols for c in split_policy(p)]
                    indexed_count = rebuild(all_chunks, DB_PATH.parent / 'chroma')
                    st.success(f"✅ Successfully indexed {indexed_count} policy chunks across {len(pols)} policy documents into ChromaDB!")
                except Exception as reb_err:
                    st.error(f"Failed to rebuild index: {reb_err}")

    if st.button("Ask Assistant", type="primary"):
        if not custom_q.strip():
            st.warning("Please type a policy question.")
        else:
            with st.spinner(f"Retrieving policy evidence and prompting local LLM ({active_llm})..."):
                try:
                    from rag.assistant import ask
                    ans = ask(custom_q.strip(), on=as_of_dt, llm_model=active_llm)

                    st.markdown(f"### Answer (Model: `{ans.get('llm_model', active_llm)}`)")
                    st.write(ans["answer"])

                    if ans["sources"]:
                        st.markdown("### 📚 Grounded Policy Citations")
                        st.dataframe(pd.DataFrame(ans["sources"]), use_container_width=True, hide_index=True)
                    else:
                        st.info("No sources cited (model abstained or query is unsupported).")

                    if ans.get("warnings"):
                        for w in ans["warnings"]:
                            st.warning(f"⚠️ Policy Warning: {w}")
                except Exception as ex:
                    st.error(f"RAG Assistant execution note: {ex}. Ensure local Ollama is running or inspect ChromaDB indexing.")

# ==============================================================================
# 8. MANAGER REVIEW & COVERAGE
# ==============================================================================
elif page == "Manager Review & Coverage":
    st.header("👥 Manager Review & Team Workforce Planning")
    st.warning("⚖️ **Human Decision-Making Authority**: AI recommendations and coverage calculations provide deterministic decision support. "
               "Managers retain full authority to approve or decline requests.")

    m_dash = manager_dashboard(actor)
    st.subheader(f"Team: {m_dash['team']['name']} (Min Coverage: {m_dash['team']['minimum_coverage_percent']}%)")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Active Team Headcount", m_dash["team"]["active_headcount"])
    mc2.metric("Pending Leave Requests", len(m_dash["pending_requests"]))
    mc3.metric("Project Deadlines", len(m_dash["deadlines"]))

    # Low-coverage warnings banner
    if m_dash.get("low_coverage_warnings"):
        st.error(f"⚠️ **Low-Coverage Warning**: {len(m_dash['low_coverage_warnings'])} date(s) in the next 30 days fall below minimum required team coverage ({m_dash['team']['minimum_coverage_percent']}%)!")
        with st.expander("🔎 Inspect Low-Coverage Warning Dates"):
            st.dataframe(pd.DataFrame(m_dash["low_coverage_warnings"]), use_container_width=True, hide_index=True)

    # Pending approval deadlines banner
    if m_dash.get("pending_approval_deadlines"):
        overdue_items = [d for d in m_dash["pending_approval_deadlines"] if d["is_overdue"]]
        if overdue_items:
            st.warning(f"🚨 **Pending Approval SLA Alert**: {len(overdue_items)} request(s) are overdue past their approval due date.")

    st.markdown("### Pending Leave Requests for Decision")
    if m_dash["pending_requests"]:
        df_p = pd.DataFrame(m_dash["pending_requests"])
        st.dataframe(df_p, use_container_width=True, hide_index=True)

        selected_req_id = st.selectbox("Select Request to Review", [r["request_id"] for r in m_dash["pending_requests"]])

        if st.button("🔍 Evaluate Workforce Impact & Coverage"):
            try:
                eval_res = evaluate_leave_request(selected_req_id)
                st.session_state["active_evaluation"] = eval_res
            except Exception as e:
                st.error(f"Evaluation error: {e}")

        if st.session_state.get("active_evaluation", {}).get("request_id") == selected_req_id:
            eval_data = st.session_state["active_evaluation"]

            st.markdown("---")
            st.markdown("### 🤖 Advisory AI Recommendation & Evidence")
            st.caption("Deterministic decision support only. Autonomous approval is permanently disabled by system policy.")

            # --- Recommendation label banner ---
            rec_label = eval_data.get("recommendation_label", eval_data["recommendation"])
            rec_code = eval_data["recommendation"]
            if rec_code == "low_risk":
                st.success(f"✅ **AI Advisory Recommendation: {rec_label}**")
            elif rec_code == "review_required":
                st.warning(f"🔍 **AI Advisory Recommendation: {rec_label}**")
            else:
                st.error(f"⛔ **AI Advisory Recommendation: {rec_label}**")

            # --- Rationale bullets ---
            st.markdown("#### 📋 Evaluation Rationale")
            for reason_line in eval_data["reasons"]:
                st.markdown(f"- {reason_line}")

            # --- Policy rules evaluated ---
            st.markdown("#### 📏 Policy Rules Evaluated")
            rules = eval_data.get("rules_evaluated", [])
            if rules:
                rules_df = pd.DataFrame([{
                    "Rule": r["rule"],
                    "Requirement": r["policy_requirement"],
                    "Observed": r["observed"],
                    "Status": r["status"],
                    "Detail": r["detail"],
                } for r in rules])
                st.dataframe(rules_df, use_container_width=True, hide_index=True)
            else:
                st.info("No detailed rule breakdown available.")

            # --- Missing information ---
            missing = eval_data.get("missing_information", [])
            if missing:
                st.markdown("#### ⚠️ Missing Information (Manager Must Resolve Before Deciding)")
                for item in missing:
                    st.warning(f"• {item}")

            # --- Attendance context ---
            att_ctx = eval_data.get("attendance_context", {})
            if att_ctx:
                with st.expander("📊 Contextual Attendance (Last 30 Days) — Not for Disciplinary Use"):
                    att_col1, att_col2, att_col3, att_col4 = st.columns(4)
                    att_col1.metric("Logged Days", att_ctx.get("total_logged_days", 0))
                    att_col2.metric("Present Days", att_ctx.get("present_days", 0))
                    att_col3.metric("Absent Days", att_ctx.get("absent_days", 0))
                    att_col4.metric("Attendance Rate", f"{att_ctx.get('attendance_rate_percent', 100)}%")
                    st.caption(f"⚠️ {att_ctx.get('disclaimer', '')}")

            # --- Critical deadlines & backup status ---
            deadlines_ev = eval_data.get("evidence", {}).get("project_deadlines", [])
            if deadlines_ev:
                st.markdown("#### 🗓️ Critical Deadlines During Leave Period")
                dl_data = []
                for d in deadlines_ev:
                    dl_data.append({
                        "Title": d["title"],
                        "Due Date": d["due_on"],
                        "Critical": "🔴 YES" if d["critical"] else "⚪ No",
                        "Requester is Owner": "✅" if d["requester_is_owner"] else "—",
                        "Backup Assigned": d.get("backup_name") or "NONE",
                        "Backup Available": ("✅" if d.get("backup_available_on_due_date") else
                                             ("⚠️ NOT AVAILABLE" if d.get("backup_employee_id") else "❌ NOT ASSIGNED")),
                        "Risk Level": d["risk"].replace("_", " ").title(),
                    })
                st.dataframe(pd.DataFrame(dl_data), use_container_width=True, hide_index=True)

            # --- Day-by-day coverage ---
            with st.expander("📅 Day-by-Day Coverage Evidence (Before / After Request)"):
                daily_cov = eval_data.get("evidence", {}).get("daily_coverage", [])
                if daily_cov:
                    cov_df = pd.DataFrame([{
                        "Date": d["date"],
                        "Total Team": d["total_active_employees"],
                        "Available (before)": d["available_before_request"],
                        "Available (after)": d["available_after_request"],
                        "Coverage % (after)": d["coverage_percent_after_request"],
                        "Min Required %": d["minimum_coverage_percent"],
                        "Meets Minimum": "✅" if d["meets_minimum"] else "❌ BREACH",
                    } for d in daily_cov])
                    st.dataframe(cov_df, use_container_width=True, hide_index=True)
                    breach_dates = eval_data.get("coverage_breach_dates", [])
                    if breach_dates:
                        st.error(f"Coverage breach on: {', '.join(breach_dates)}")
                else:
                    st.info("No working days found in the requested period (weekend/holiday span).")

        st.markdown("---")
        st.markdown("### ⚖️ Authorized Human Manager Decision")
        st.caption("The final approval or rejection must be made by a human manager or HR. Your decision and explanatory note are preserved in the audit log.")
        with st.form("decision_form"):
            dec_choice = st.radio("Manager Decision", ["approved", "declined"], horizontal=True)
            dec_note = st.text_area("Decision Rationale & Explanatory Note (Preserved in Decision History)",
                                    placeholder="Provide business justification, backup coverage confirmation, or reason for decline")
            record_btn = st.form_submit_button("Record Human Decision", use_container_width=True)

        if record_btn:
            try:
                if flask_connected:
                    api_client.decide_leave_request(
                        actor=actor,
                        request_id=selected_req_id,
                        decision=dec_choice,
                        note=dec_note,
                        decided_on=date.today().isoformat()
                    )
                else:
                    decide_leave_request(
                        request_id=selected_req_id,
                        decision=dec_choice,
                        decided_by=actor.employee_id,
                        note=dec_note,
                        decided_on=date.today().isoformat()
                    )
                dec_via = " (via Flask REST API)" if flask_connected else ""
                st.success(f"Human decision '{dec_choice.upper()}' successfully recorded{dec_via} by manager {actor.employee_id} for request #{selected_req_id} and archived into decision history.")
                if "active_evaluation" in st.session_state:
                    del st.session_state["active_evaluation"]
                st.rerun()
            except Exception as ex:
                st.error(f"Decision failed: {ex}")

        # Display Decision History and Audit Trail
        try:
            hist_records = get_decision_history(selected_req_id)
            if hist_records:
                with st.expander(f"📜 View Complete Decision History & Audit Trail for Request #{selected_req_id}", expanded=False):
                    hist_display = []
                    for h in hist_records:
                        hist_display.append({
                            "Entry ID": h["decision_id"],
                            "Type": "🤖 AI Evaluation" if h["is_ai_recommendation"] else "⚖️ Human Decision",
                            "Recommendation / Decision": h["recommendation"] if h["is_ai_recommendation"] else f"Decision: {h['final_decision'].upper()}",
                            "Decided / Evaluated By": "AI System" if h["is_ai_recommendation"] else f"{h['decided_by']} ({h.get('decided_by_name') or 'Manager'})",
                            "Date": h["decided_on"] or "Evaluation Time",
                            "Note / Justification": h["note"] or "—"
                        })
                    st.dataframe(pd.DataFrame(hist_display), use_container_width=True, hide_index=True)
        except Exception as h_err:
            st.caption(f"Could not load decision history: {h_err}")
    else:
        st.info("No pending requests awaiting manager decision.")

    # Team Comp-off Balances
    st.markdown("---")
    st.subheader("💳 Team Compensatory Off Balances & Upcoming Expiries")
    tc_tab1, tc_tab2 = st.tabs(["Team Comp-off Balances", "Upcoming Expiries (Next 30 Days)"])
    with tc_tab1:
        if m_dash.get("comp_off_balances"):
            st.dataframe(pd.DataFrame(m_dash["comp_off_balances"]), use_container_width=True, hide_index=True)
        else:
            st.info("No comp-off balances on record for this team.")
    with tc_tab2:
        if m_dash.get("upcoming_compoff_expiries"):
            st.warning(f"Found {len(m_dash['upcoming_compoff_expiries'])} comp-off entitlement(s) expiring within 30 days:")
            st.dataframe(pd.DataFrame(m_dash["upcoming_compoff_expiries"]), use_container_width=True, hide_index=True)
        else:
            st.success("✅ No team comp-off days are expiring in the next 30 days.")

    st.markdown("---")
    st.subheader("🎯 Critical Deadlines & Backup Candidate Identification")
    if m_dash["deadlines"]:
        st.dataframe(pd.DataFrame(m_dash["deadlines"]), use_container_width=True, hide_index=True)
        pick_dl = st.selectbox("Select Deadline to Identify Backups", [d["deadline_id"] for d in m_dash["deadlines"]])
        if st.button("Identify Available Backup Candidates"):
            try:
                recs = recommend_backups(pick_dl)
                st.dataframe(pd.DataFrame(recs), use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(str(e))
    else:
        st.info("No project deadlines on record for this team.")

    st.markdown("---")
    st.subheader("🔮 What-If Analysis: Compare Team Coverage for Alternative Dates (Bonus)")
    st.caption("Simulate hypothetical absences for one or more team members across candidate date ranges to evaluate coverage impact, threshold breaches, and deadline conflicts.")

    with connection() as conn:
        team_members = [dict(r) for r in conn.execute(
            "SELECT employee_id, name, role FROM employees WHERE team_id=? AND is_active=1 ORDER BY employee_id",
            (m_dash["team"]["team_id"],)
        )]

    wi_col1, wi_col2 = st.columns([1, 1])
    with wi_col1:
        selected_candidates = st.multiselect(
            "Select Team Members to Simulate Absence",
            options=[e["employee_id"] for e in team_members],
            format_func=lambda eid: next((f"{e['employee_id']} - {e['name']}" for e in team_members if e["employee_id"] == eid), eid),
            default=[team_members[0]["employee_id"]] if team_members else []
        )
        wi_thresh = st.slider(
            "Configurable Minimum Coverage Threshold (%)",
            min_value=10, max_value=100,
            value=int(m_dash["team"]["minimum_coverage_percent"]),
            step=5
        )

    with wi_col2:
        wi_start = st.date_input("Hypothetical Leave Start", date.today() + timedelta(days=2), key="wi_start")
        wi_end = st.date_input("Hypothetical Leave End", date.today() + timedelta(days=6), key="wi_end")

    if st.button("🚀 Run What-If Simulation", use_container_width=True):
        if not selected_candidates:
            st.warning("Please select at least one employee to simulate absence.")
        elif wi_end < wi_start:
            st.error("End date cannot be earlier than start date.")
        else:
            try:
                sim_res = simulate_what_if_leave(
                    team_id=m_dash["team"]["team_id"],
                    candidate_employee_ids=selected_candidates,
                    start_date=wi_start,
                    end_date=wi_end,
                    threshold_percent=wi_thresh
                )

                st.markdown("#### Simulation Findings")
                if sim_res["is_feasible"]:
                    st.success(f"✅ **Simulation Passed**: Proposed leave is feasible! Coverage remains at or above {wi_thresh}% on all working days, and no critical deadlines are left unassigned.")
                else:
                    st.error(f"⚠️ **Simulation Flagged Risks**: Lowest coverage drops to {sim_res['lowest_simulated_coverage_percent']}% ({sim_res['breach_days_count']} breach days). Critical deadlines at risk: {len(sim_res['at_risk_deadlines'])}.")

                sm1, sm2, sm3, sm4 = st.columns(4)
                sm1.metric("Lowest Simulated Coverage", f"{sim_res['lowest_simulated_coverage_percent']}%")
                sm2.metric("Breach Working Days", sim_res["breach_days_count"])
                sm3.metric("Evaluated Days", sim_res["total_evaluated_days"])
                sm4.metric("Deadlines at Risk", len(sim_res["at_risk_deadlines"]))

                if sim_res["recommendations"]:
                    st.markdown("**Actionable Suggestions:**")
                    for rec in sim_res["recommendations"]:
                        st.markdown(f"- {rec}")

                if sim_res["at_risk_deadlines"]:
                    st.markdown("##### 🚨 Critical Deadlines Impacted")
                    st.dataframe(pd.DataFrame(sim_res["at_risk_deadlines"]), use_container_width=True, hide_index=True)

                st.markdown("##### 📅 Daily Day-by-Day Coverage Comparison")
                df_daily = pd.DataFrame(sim_res["daily_breakdown"])[[
                    "date", "weekday", "is_working_day", "baseline_available", "simulated_available",
                    "total_headcount", "baseline_coverage_percent", "simulated_coverage_percent", "meets_threshold"
                ]]
                st.dataframe(df_daily, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"What-If Simulation error: {e}")

# ==============================================================================
# 9. HR EMPLOYEE ADMIN
# ==============================================================================
elif page == "HR Employee Admin":
    st.header("👥 HR Employee Administration")

    admin_tab1, admin_tab2 = st.tabs(["Create New Employee", "Employee Directory & Provisioning"])

    with admin_tab1:
        st.subheader("Register New Synthetic Employee")
        with st.form("create_emp_form"):
            ne_id = st.text_input("Employee ID", placeholder="e.g. E012")
            ne_name = st.text_input("Full Name", placeholder="e.g. Ananya Sharma")
            ne_email = st.text_input("Company Email", placeholder="e.g. ananya@company.test")
            ne_role = st.selectbox("Role", ["employee", "manager", "hr"])
            ne_team = st.selectbox("Team ID", ["T01", "T02"])
            ne_mgr = st.text_input("Manager Employee ID (Optional)", placeholder="e.g. E005")
            ne_join = st.date_input("Joining Date", date.today())
            create_btn = st.form_submit_button("Create Employee")

        if create_btn:
            try:
                created = create_employee(
                    actor,
                    employee_id=ne_id,
                    name=ne_name,
                    email=ne_email,
                    role=ne_role,
                    team_id=ne_team,
                    manager_id=ne_mgr.strip() or None,
                    joined_on=ne_join.isoformat()
                )
                st.success(f"Employee {created['name']} ({created['employee_id']}) registered successfully.")
                st.rerun()
            except Exception as ex:
                st.error(f"Creation failed: {ex}")

    with admin_tab2:
        st.subheader("Organization Employee Directory")
        all_emps = list_all_employees(actor)
        st.dataframe(pd.DataFrame(all_emps), use_container_width=True, hide_index=True)

        st.markdown("### Set or Reset Employee Password")
        with st.form("set_pwd_form"):
            t_user = st.selectbox("Select Employee", [f"{e['employee_id']} — {e['name']} ({e['role']})" for e in all_emps if e["is_active"]])
            new_pwd = st.text_input("New Password", type="password")
            save_pwd = st.form_submit_button("Update Password")

        if save_pwd:
            try:
                emp_target = t_user.split(" — ")[0]
                set_employee_password(actor, emp_target, new_pwd)
                st.success(f"Password updated for {emp_target}.")
            except Exception as ex:
                st.error(str(ex))

        st.markdown("### Deactivate Employee Account")
        with st.form("deact_form"):
            d_user = st.selectbox("Select Employee to Deactivate", [f"{e['employee_id']} — {e['name']}" for e in all_emps if e["is_active"] and e["employee_id"] != actor.employee_id])
            deact_btn = st.form_submit_button("Deactivate Account")

        if deact_btn:
            try:
                deact_target = d_user.split(" — ")[0]
                res = deactivate_employee(actor, deact_target)
                st.success(f"Account for {deact_target} deactivated.")
                st.rerun()
            except Exception as ex:
                st.error(str(ex))

# ==============================================================================
# 10. SYSTEM AUDIT LOGS
# ==============================================================================
elif page == "System Audit Logs":
    st.header("🛡️ System Security & Workflow Audit Trail")
    st.write("All authentication, leave approval, comp-off grants, employee management, and configuration changes are permanently logged.")

    try:
        logs = get_audit_logs(actor, limit=100)
        if logs:
            st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
        else:
            st.info("No audit logs recorded yet.")
    except Exception as ex:
        st.error(f"Error loading audit trail: {ex}")
