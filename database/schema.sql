PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    min_coverage_percent INTEGER NOT NULL DEFAULT 60 CHECK (min_coverage_percent BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr')),
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    manager_id TEXT REFERENCES employees(employee_id),
    joined_on TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS policy_documents (
    policy_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    file_path TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE(title, version),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS leave_balances (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    leave_type TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick')),
    year INTEGER NOT NULL,
    entitled_days REAL NOT NULL CHECK (entitled_days >= 0),
    used_days REAL NOT NULL DEFAULT 0 CHECK (used_days >= 0),
    PRIMARY KEY(employee_id, leave_type, year),
    CHECK (used_days <= entitled_days)
);

CREATE TABLE IF NOT EXISTS holidays (
    holiday_id INTEGER PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    holiday_type TEXT NOT NULL CHECK (holiday_type IN ('public', 'optional'))
);

CREATE TABLE IF NOT EXISTS leave_requests (
    request_id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    leave_type TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'comp_off')),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    requested_days REAL NOT NULL CHECK (requested_days > 0),
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('draft', 'pending', 'needs_review', 'approved', 'declined')),
    submitted_on TEXT NOT NULL,
    approval_due_on TEXT,
    decided_by TEXT REFERENCES employees(employee_id),
    decided_on TEXT,
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS attendance (
    attendance_id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'approved_leave')),
    check_in TEXT,
    check_out TEXT,
    UNIQUE(employee_id, date)
);

CREATE TABLE IF NOT EXISTS comp_off_records (
    comp_off_id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    earned_on TEXT NOT NULL,
    expires_on TEXT NOT NULL,
    days REAL NOT NULL DEFAULT 1 CHECK (days > 0),
    status TEXT NOT NULL CHECK (status IN ('available', 'used', 'expired')),
    used_on TEXT,
    work_reference TEXT,
    CHECK (expires_on >= earned_on),
    CHECK ((status = 'used' AND used_on IS NOT NULL) OR (status != 'used' AND used_on IS NULL))
);

CREATE TABLE IF NOT EXISTS project_deadlines (
    deadline_id INTEGER PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    title TEXT NOT NULL,
    due_on TEXT NOT NULL,
    critical INTEGER NOT NULL DEFAULT 1 CHECK (critical IN (0, 1)),
    owner_id TEXT NOT NULL REFERENCES employees(employee_id)
);

CREATE TABLE IF NOT EXISTS backup_assignments (
    assignment_id INTEGER PRIMARY KEY,
    deadline_id INTEGER NOT NULL UNIQUE REFERENCES project_deadlines(deadline_id),
    backup_employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    assigned_on TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_history (
    decision_id INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES leave_requests(request_id),
    recommendation TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    final_decision TEXT CHECK (final_decision IN ('approved', 'declined')),
    decided_by TEXT REFERENCES employees(employee_id),
    decided_on TEXT,
    note TEXT,
    CHECK ((final_decision IS NULL AND decided_by IS NULL AND decided_on IS NULL)
        OR (final_decision IS NOT NULL AND decided_by IS NOT NULL AND decided_on IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INTEGER PRIMARY KEY,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action TEXT NOT NULL,
    target_record TEXT,
    details TEXT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_leave_employee_dates ON leave_requests(employee_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_leave_status ON leave_requests(status);
CREATE INDEX IF NOT EXISTS idx_attendance_employee_date ON attendance(employee_id, date);
CREATE INDEX IF NOT EXISTS idx_deadlines_team_date ON project_deadlines(team_id, due_on);
CREATE INDEX IF NOT EXISTS idx_compoff_employee_expiry ON comp_off_records(employee_id, expires_on);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_id);

-- Structured timeline items. Alerts are derived from persisted records.
CREATE TABLE IF NOT EXISTS timeline_items (
    item_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    due_on TEXT NOT NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('project_deadline','approval_deadline','return_to_work','notice_deadline','other')),
    employee_id TEXT REFERENCES employees(employee_id),
    team_id TEXT REFERENCES teams(team_id),
    details TEXT,
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'cancelled')),
    reminder_date TEXT,
    created_by TEXT NOT NULL REFERENCES employees(employee_id),
    created_on TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_timeline_due ON timeline_items(due_on, item_type);
