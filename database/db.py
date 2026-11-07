"""SQLite connection and schema initialization."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'hr_assistant.db'
SCHEMA_PATH = Path(__file__).with_name('schema.sql')


@contextmanager
def connection(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(db_path: Path = DB_PATH):
    with connection(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        # Safe migrations for existing databases
        att_cols = {col['name'] for col in conn.execute("PRAGMA table_info(attendance)").fetchall()}
        if 'check_in' not in att_cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN check_in TEXT")
        if 'check_out' not in att_cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN check_out TEXT")

        comp_cols = {col['name'] for col in conn.execute("PRAGMA table_info(comp_off_records)").fetchall()}
        if 'work_reference' not in comp_cols:
            conn.execute("ALTER TABLE comp_off_records ADD COLUMN work_reference TEXT")

        tl_cols = {col['name'] for col in conn.execute("PRAGMA table_info(timeline_items)").fetchall()}
        if 'priority' not in tl_cols:
            conn.execute("ALTER TABLE timeline_items ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
        if 'status' not in tl_cols:
            conn.execute("ALTER TABLE timeline_items ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if 'reminder_date' not in tl_cols:
            conn.execute("ALTER TABLE timeline_items ADD COLUMN reminder_date TEXT")

        conn.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY,
            actor_id TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            action TEXT NOT NULL,
            target_record TEXT,
            details TEXT,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def log_audit(actor_id: str, actor_role: str, action: str,
              target_record: str = "", details: str = "",
              db_path: Path = DB_PATH) -> int:
    """Record an audit trail event for security, compliance and accountability."""
    with connection(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO audit_logs(actor_id, actor_role, action, target_record, details)
               VALUES (?, ?, ?, ?, ?)""",
            (actor_id, actor_role, action, target_record, details),
        )
        return int(cursor.lastrowid)

