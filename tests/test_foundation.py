"""Phase 1 schema and seed-data checks."""
import sqlite3
from pathlib import Path
from database.db import connection, initialize
from database.seed import seed


def test_schema_enforces_foreign_keys(tmp_path: Path):
    db_path = tmp_path / 'test.db'
    initialize(db_path)
    with connection(db_path) as conn:
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        try:
            conn.execute("INSERT INTO employees(employee_id, name, email, role, team_id, joined_on) VALUES ('X', 'X', 'x@example.test', 'employee', 'MISSING', '2026-01-01')")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError('Foreign key violation was accepted')


def test_synthetic_data(tmp_path: Path):
    db_path = tmp_path / 'synthetic_data.db'
    seed(db_path)
    with connection(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees WHERE role != 'hr'").fetchone()[0] == 10
        assert conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0] >= 10
        assert conn.execute('SELECT COUNT(*) FROM teams').fetchone()[0] >= 2
        assert conn.execute('SELECT COUNT(*) FROM leave_balances').fetchone()[0] >= 20
        assert conn.execute('SELECT COUNT(*) FROM policy_documents').fetchone()[0] >= 2
        assert conn.execute('SELECT COUNT(*) FROM attendance').fetchone()[0] > 0
        assert conn.execute('SELECT COUNT(*) FROM project_deadlines').fetchone()[0] == 3
        assert conn.execute('SELECT COUNT(*) FROM backup_assignments').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM leave_requests WHERE status = ?', ('pending',)).fetchone()[0] >= 1


def test_seed_is_repeatable(tmp_path: Path):
    db_path = tmp_path / 'repeatable_seed.db'
    seed(db_path)
    seed(db_path)
    with connection(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees WHERE role != 'hr'").fetchone()[0] == 10
        assert conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0] >= 10
