from __future__ import annotations
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional, Tuple, List, Dict, Any
from database.db import DB_PATH, connection, log_audit

ROLES = {"employee", "manager", "hr"}

class AccessError(PermissionError):
    """Raised when authentication or authorization fails."""

@dataclass(frozen=True)
class UserContext:
    employee_id: str
    name: str
    role: Literal["employee", "manager", "hr"]
    team_id: str


def _password_hash(password: str, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    if not isinstance(password, str) or len(password) < 10:
        raise AccessError("Password must contain at least 10 characters.")
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return salt, digest


def initialize_security(db_path=DB_PATH) -> None:
    """Create credential storage without changing existing HR business tables."""
    with connection(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS user_credentials (
            employee_id TEXT PRIMARY KEY REFERENCES employees(employee_id),
            password_salt BLOB NOT NULL,
            password_hash BLOB NOT NULL,
            created_on TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def bootstrap_hr(employee_id: str, password: str, db_path=DB_PATH) -> None:
    """Set the first HR password only when no credentials exist yet.

    Run locally during initial setup. Subsequent credential management must be
    performed by an authenticated HR user through set_employee_password().
    """
    salt, digest = _password_hash(password)
    with connection(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS user_credentials (
            employee_id TEXT PRIMARY KEY REFERENCES employees(employee_id),
            password_salt BLOB NOT NULL, password_hash BLOB NOT NULL,
            created_on TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        if conn.execute("SELECT 1 FROM user_credentials LIMIT 1").fetchone():
            raise AccessError("Security is already bootstrapped.")
        user = conn.execute("SELECT role,is_active FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
        if user is None or user["role"] != "hr" or not user["is_active"]:
            raise AccessError("Bootstrap account must be an active HR employee.")
        conn.execute("INSERT INTO user_credentials(employee_id,password_salt,password_hash) VALUES(?,?,?)",
                     (employee_id, salt, digest))
    log_audit(employee_id, "hr", "bootstrap_hr", employee_id, "Bootstrapped initial HR credentials", db_path)


def set_employee_password(actor: UserContext, employee_id: str, password: str, db_path=DB_PATH) -> None:
    """HR-only credential provisioning/reset for an existing active employee."""
    require_role(actor, "hr")
    salt, digest = _password_hash(password)
    with connection(db_path) as conn:
        target = conn.execute("SELECT is_active, name FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
        if target is None or not target["is_active"]:
            raise AccessError("Target employee does not exist or is inactive.")
        conn.execute("""INSERT INTO user_credentials(employee_id,password_salt,password_hash)
            VALUES(?,?,?) ON CONFLICT(employee_id) DO UPDATE SET
            password_salt=excluded.password_salt,password_hash=excluded.password_hash""",
            (employee_id, salt, digest))
    log_audit(actor.employee_id, actor.role, "set_password", employee_id, f"Set password for employee {target['name']}", db_path)


def authenticate(employee_id: str, password: str, db_path=DB_PATH) -> UserContext:
    """Verify credentials and return trusted identity data from the database."""
    initialize_security(db_path)
    with connection(db_path) as conn:
        row = conn.execute("""SELECT e.employee_id,e.name,e.role,e.team_id,e.is_active,
            c.password_salt,c.password_hash FROM employees e
            JOIN user_credentials c ON c.employee_id=e.employee_id
            WHERE e.employee_id=?""", (employee_id,)).fetchone()
    if row is None or not row["is_active"]:
        log_audit(employee_id, "unknown", "auth_failed", employee_id, "Invalid credentials or inactive account", db_path)
        raise AccessError("Invalid employee ID or password.")
    candidate = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"),
                                    bytes(row["password_salt"]), 310_000)
    if not hmac.compare_digest(candidate, bytes(row["password_hash"])):
        log_audit(employee_id, row["role"], "auth_failed", employee_id, "Password verification failed", db_path)
        raise AccessError("Invalid employee ID or password.")
    log_audit(row["employee_id"], row["role"], "auth_success", row["employee_id"], "Successful login", db_path)
    return UserContext(row["employee_id"], row["name"], row["role"], row["team_id"])


def require_role(actor: UserContext, *allowed: str) -> None:
    if actor.role not in allowed:
        raise AccessError("You do not have permission to perform this action.")


def can_access_employee(actor: UserContext, employee_id: str, db_path=DB_PATH) -> bool:
    if actor.role == "hr":
        return True
    if actor.employee_id == employee_id:
        return True
    if actor.role != "manager":
        return False
    with connection(db_path) as conn:
        row = conn.execute("SELECT team_id FROM employees WHERE employee_id=? AND is_active=1",
                           (employee_id,)).fetchone()
    return row is not None and row["team_id"] == actor.team_id


def require_employee_scope(actor: UserContext, employee_id: str, db_path=DB_PATH) -> None:
    if not can_access_employee(actor, employee_id, db_path):
        raise AccessError("You cannot access this employee's information.")


# HR Employee Management Functions

def create_employee(actor: UserContext, employee_id: str, name: str, email: str,
                    role: str, team_id: str, manager_id: Optional[str] = None,
                    joined_on: Optional[str] = None, initial_annual: float = 18.0,
                    initial_sick: float = 10.0, initial_password: Optional[str] = None,
                    db_path=DB_PATH) -> Dict[str, Any]:
    """HR-only creation of a new synthetic employee record and leave balances."""
    require_role(actor, "hr")
    emp_id = employee_id.strip()
    emp_name = name.strip()
    emp_email = email.strip()
    emp_role = role.strip().lower()
    t_id = team_id.strip()
    join_date = joined_on or date.today().isoformat()
    if not emp_id or not emp_name or not emp_email:
        raise ValueError("Employee ID, name, and email are required.")
    if emp_role not in ROLES:
        raise ValueError(f"Role must be one of {sorted(ROLES)}.")
    year = int(join_date[:4])
    with connection(db_path) as conn:
        team = conn.execute("SELECT 1 FROM teams WHERE team_id=?", (t_id,)).fetchone()
        if not team:
            raise ValueError(f"Unknown team ID: {t_id}")
        if manager_id:
            mgr = conn.execute("SELECT 1 FROM employees WHERE employee_id=? AND is_active=1", (manager_id,)).fetchone()
            if not mgr:
                raise ValueError(f"Manager {manager_id} not found or inactive.")
        conn.execute("""INSERT INTO employees
            (employee_id, name, email, role, team_id, manager_id, joined_on, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (emp_id, emp_name, emp_email, emp_role, t_id, manager_id, join_date))
        conn.execute("""INSERT INTO leave_balances
            (employee_id, leave_type, year, entitled_days, used_days)
            VALUES (?, 'annual', ?, ?, 0), (?, 'sick', ?, ?, 0)""",
            (emp_id, year, initial_annual, emp_id, year, initial_sick))
        if initial_password is not None:
            salt, digest = _password_hash(initial_password)
            conn.execute("""INSERT INTO user_credentials(employee_id,password_salt,password_hash)
                VALUES(?,?,?) ON CONFLICT(employee_id) DO UPDATE SET
                password_salt=excluded.password_salt,password_hash=excluded.password_hash""",
                (emp_id, salt, digest))
    log_audit(actor.employee_id, actor.role, "create_employee", emp_id, f"Created {emp_role} {emp_name}", db_path)
    return {
        "employee_id": emp_id,
        "name": emp_name,
        "email": emp_email,
        "role": emp_role,
        "team_id": t_id,
        "manager_id": manager_id,
        "joined_on": join_date,
        "is_active": 1
    }


def deactivate_employee(actor: UserContext, employee_id: str, db_path=DB_PATH) -> Dict[str, Any]:
    """HR-only deactivation of an employee account."""
    require_role(actor, "hr")
    if actor.employee_id == employee_id:
        raise ValueError("Cannot deactivate your own HR account.")
    with connection(db_path) as conn:
        target = conn.execute("SELECT name FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
        if not target:
            raise ValueError(f"Employee {employee_id} not found.")
        conn.execute("UPDATE employees SET is_active=0 WHERE employee_id=?", (employee_id,))
    log_audit(actor.employee_id, actor.role, "deactivate_employee", employee_id, f"Deactivated {target['name']}", db_path)
    return {
        "employee_id": employee_id,
        "name": target["name"],
        "is_active": 0,
        "message": f"Employee {employee_id} deactivated successfully"
    }


def list_all_employees(actor: UserContext, team_id: Optional[str] = None,
                       is_active: Optional[bool] = None, db_path=DB_PATH) -> List[Dict[str, Any]]:
    """List employees scoped by role: HR sees all, Manager sees team, Employee sees self."""
    with connection(db_path) as conn:
        query = """SELECT e.employee_id, e.name, e.email, e.role, e.team_id, t.name as team_name,
                          e.manager_id, m.name as manager_name, e.joined_on, e.is_active
                   FROM employees e
                   JOIN teams t ON t.team_id = e.team_id
                   LEFT JOIN employees m ON m.employee_id = e.manager_id WHERE 1=1"""
        params: List[Any] = []
        if actor.role == "employee":
            query += " AND e.employee_id = ?"
            params.append(actor.employee_id)
        elif actor.role == "manager":
            query += " AND e.team_id = ?"
            params.append(actor.team_id)
        else:
            if team_id:
                query += " AND e.team_id = ?"
                params.append(team_id)
        if is_active is not None:
            query += " AND e.is_active = ?"
            params.append(1 if is_active else 0)
        query += " ORDER BY e.team_id, e.employee_id"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_audit_logs(actor: UserContext, limit: int = 100, action_filter: Optional[str] = None,
                   db_path=DB_PATH) -> List[Dict[str, Any]]:
    """HR-only query of audit logs for accountability and compliance."""
    require_role(actor, "hr")
    with connection(db_path) as conn:
        if action_filter:
            rows = conn.execute(
                """SELECT log_id, actor_id, actor_role, action, target_record, details, timestamp
                   FROM audit_logs WHERE action = ? ORDER BY timestamp DESC, log_id DESC LIMIT ?""",
                (action_filter, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT log_id, actor_id, actor_role, action, target_record, details, timestamp
                   FROM audit_logs ORDER BY timestamp DESC, log_id DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
