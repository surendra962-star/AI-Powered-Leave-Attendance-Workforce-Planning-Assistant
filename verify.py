"""Print a concise summary of the initialized database."""
from database.db import connection

TABLES = ('teams', 'employees', 'policy_documents', 'leave_balances', 'leave_requests',
          'attendance', 'holidays', 'comp_off_records', 'project_deadlines',
          'backup_assignments', 'decision_history', 'audit_logs', 'timeline_items')

with connection() as conn:
    for table in TABLES:
        count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f'{table:22} {count:>4}')
