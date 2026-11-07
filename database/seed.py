"""Repeatable synthetic data setup; never uses real employee data."""
from datetime import date, timedelta
from pathlib import Path
from database.db import DB_PATH, connection, initialize

YEAR = 2026

DEMO_CREDENTIALS = {
    'HR001': 'hradmin@2026',
    'E005': 'kiranmgr@2026',
    'E001': 'rahuluser@2026',
    'E010': 'vikrammgr@2026',
    'E006': 'raviuser@2026',
}


def _seed_credentials(conn):
    from access_control.service import _password_hash
    conn.execute("""CREATE TABLE IF NOT EXISTS user_credentials (
        employee_id TEXT PRIMARY KEY REFERENCES employees(employee_id),
        password_salt BLOB NOT NULL,
        password_hash BLOB NOT NULL,
        created_on TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    for emp_id, pwd in DEMO_CREDENTIALS.items():
        existing = conn.execute("SELECT 1 FROM user_credentials WHERE employee_id=?", (emp_id,)).fetchone()
        if not existing:
            emp = conn.execute("SELECT 1 FROM employees WHERE employee_id=?", (emp_id,)).fetchone()
            if emp:
                salt, digest = _password_hash(pwd)
                conn.execute("INSERT OR REPLACE INTO user_credentials(employee_id, password_salt, password_hash) VALUES (?, ?, ?)",
                             (emp_id, salt, digest))


def seed(db_path: Path = DB_PATH, force: bool = False):
    initialize(db_path)
    with connection(db_path) as conn:
        emp_count = conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
        if emp_count and not force:
            hr_exists = conn.execute("SELECT 1 FROM employees WHERE employee_id='HR001'").fetchone()
            if not hr_exists:
                conn.execute("""INSERT OR IGNORE INTO employees
                    (employee_id, name, email, role, team_id, manager_id, joined_on, is_active)
                    VALUES ('HR001', 'HR Admin', 'hr-admin@example.test', 'hr', 'T01', NULL, '2025-07-01', 1)""")
            _seed_credentials(conn)
            print('Seed skipped: employees already exist. Ensured HR001 and demo credentials.')
            return

        conn.executemany('INSERT OR IGNORE INTO teams(team_id, name, min_coverage_percent) VALUES (?, ?, ?)', [
            ('T01', 'AI Development', 60), ('T02', 'Software Development', 60)
        ])
        people = [
            ('E001', 'Rahul', 'rahul@example.test', 'employee', 'T01', 'E005'),
            ('E002', 'Priya', 'priya@example.test', 'employee', 'T01', 'E005'),
            ('E003', 'Arun', 'arun@example.test', 'employee', 'T01', 'E005'),
            ('E004', 'Sneha', 'sneha@example.test', 'employee', 'T01', 'E005'),
            ('E005', 'Kiran', 'kiran@example.test', 'manager', 'T01', None),
            ('E006', 'Ravi', 'ravi@example.test', 'employee', 'T02', 'E010'),
            ('E007', 'Divya', 'divya@example.test', 'employee', 'T02', 'E010'),
            ('E008', 'Manoj', 'manoj@example.test', 'employee', 'T02', 'E010'),
            ('E009', 'Anjali', 'anjali@example.test', 'employee', 'T02', 'E010'),
            ('E010', 'Vikram', 'vikram@example.test', 'manager', 'T02', None),
            ('HR001', 'HR Admin', 'hr-admin@example.test', 'hr', 'T01', None),
        ]
        people.sort(key=lambda person: person[5] is not None)  # Insert managers before direct reports.
        conn.executemany('''INSERT OR REPLACE INTO employees
            (employee_id, name, email, role, team_id, manager_id, joined_on, is_active)
            VALUES (?, ?, ?, ?, ?, ?, '2025-07-01', 1)''', people)

        conn.executemany('''INSERT OR REPLACE INTO leave_balances
            (employee_id, leave_type, year, entitled_days, used_days) VALUES (?, ?, ?, ?, ?)''', [
            (p[0], kind, YEAR, entitlement, 2 if kind == 'annual' else 1)
            for p in people if p[3] != 'hr' for kind, entitlement in [('annual', 18), ('sick', 10)]
        ])
        conn.executemany('INSERT OR IGNORE INTO holidays(date, name, holiday_type) VALUES (?, ?, ?)', [
            ('2026-11-09', 'Sample Public Holiday', 'public'),
            ('2026-12-25', 'Sample Winter Holiday', 'public'),
            ('2026-11-20', 'Sample Optional Holiday', 'optional'),
        ])
        conn.executemany('''INSERT OR IGNORE INTO policy_documents
            (title, version, effective_from, effective_to, file_path, is_active)
            VALUES (?, ?, ?, ?, ?, ?)''', [
            ('Sample Leave Policy', '1.0', '2025-01-01', '2025-12-31', 'data/policies/leave_policy_v1.md', 0),
            ('Sample Leave Policy', '2.0', '2026-01-01', None, 'data/policies/leave_policy_v2.md', 1),
            ('Attendance and Remote Work Policy', '1.0', '2026-01-01', None, 'data/policies/attendance_remote_policy.pdf', 1),
        ])
        conn.executemany('''INSERT OR IGNORE INTO leave_requests
            (employee_id, leave_type, start_date, end_date, requested_days, reason, status, submitted_on, approval_due_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', [
            ('E001', 'annual', '2026-11-09', '2026-11-13', 4, 'Family event', 'pending', '2026-10-30', '2026-11-04'),
            ('E003', 'annual', '2026-11-10', '2026-11-13', 4, 'Personal', 'approved', '2026-10-20', '2026-10-23'),
            ('E004', 'annual', '2026-11-10', '2026-11-12', 3, 'Personal', 'approved', '2026-10-20', '2026-10-23'),
            ('E006', 'annual', '2026-11-16', '2026-11-20', 5, 'Travel', 'pending', '2026-10-30', '2026-11-04'),
            ('E007', 'sick', '2026-11-05', '2026-11-06', 2, 'Recovery', 'pending', '2026-11-04', '2026-11-05'),
        ])
        conn.executemany('''INSERT OR IGNORE INTO comp_off_records
            (employee_id, earned_on, expires_on, status, used_on) VALUES (?, ?, ?, ?, ?)''', [
            ('E002', '2026-08-07', '2026-11-05', 'available', None),
            ('E006', '2026-07-17', '2026-10-15', 'expired', None),
            ('E009', '2026-09-21', '2026-12-20', 'used', '2026-10-05'),
        ])
        conn.executemany('''INSERT OR IGNORE INTO project_deadlines(team_id, title, due_on, critical, owner_id)
            VALUES (?, ?, ?, ?, ?)''', [
            ('T01', 'Model evaluation delivery', '2026-11-11', 1, 'E001'),
            ('T01', 'Data pipeline release', '2026-11-12', 1, 'E003'),
            ('T02', 'API release', '2026-11-18', 1, 'E006'),
        ])
        conn.execute('''INSERT OR IGNORE INTO backup_assignments(deadline_id, backup_employee_id, assigned_on)
            VALUES (1, 'E002', '2026-10-25')''')

        start = date(2026, 10, 5)
        attendance_rows = []
        for offset in range(20):
            current = start + timedelta(days=offset)
            if current.weekday() < 5:
                for idx, p in enumerate(people):
                    if p[3] == 'hr':
                        continue
                    status = 'absent' if (idx + offset) % 17 == 0 else 'present'
                    attendance_rows.append((p[0], current.isoformat(), status))
        conn.executemany('INSERT OR IGNORE INTO attendance(employee_id, date, status) VALUES (?, ?, ?)', attendance_rows)
        _seed_credentials(conn)
    print('Synthetic dataset created successfully.')


if __name__ == '__main__':
    seed()

