from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional, List, Tuple
from database.db import DB_PATH, ROOT, connection

@dataclass(frozen=True)
class Policy:
    policy_id: int
    title: str
    version: str
    effective_from: str
    effective_to: Optional[str]
    is_active: bool
    path: Path
    text: str
    pages: Optional[List[Tuple[int, str]]] = None


def load_policies(db_path: Path = DB_PATH, root: Path = ROOT) -> List[Policy]:
    policies = []
    with connection(db_path) as conn:
        rows = conn.execute('SELECT * FROM policy_documents ORDER BY effective_from, policy_id').fetchall()
    for row in rows:
        path = (root / row['file_path']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Policy file path escapes project root')
        if not path.is_file():
            raise FileNotFoundError(f'Policy document missing: {path}')
        if path.suffix.lower() == '.pdf':
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                pages = []
                for idx, page in enumerate(reader.pages, 1):
                    p_txt = page.extract_text() or ""
                    pages.append((idx, p_txt))
                text = "\n\n".join(t for _, t in pages)
            except Exception as exc:
                text = f"[Unreadable PDF: {exc}]"
                pages = [(1, text)]
        else:
            text = path.read_text(encoding='utf-8')
            import re
            if '\x0c' in text:
                parts = text.split('\x0c')
                pages = [(i, p.strip()) for i, p in enumerate(parts, 1)]
            elif re.search(r'<!--\s*page\s*(\d+)\s*-->', text, re.IGNORECASE):
                split_parts = re.split(r'<!--\s*page\s*(\d+)\s*-->', text, flags=re.IGNORECASE)
                pages = []
                if split_parts[0].strip():
                    pages.append((1, split_parts[0].strip()))
                for i in range(1, len(split_parts), 2):
                    p_num = int(split_parts[i])
                    p_content = split_parts[i+1].strip()
                    pages.append((p_num, p_content))
            else:
                pages = [(1, text)]
        policies.append(Policy(row['policy_id'], row['title'], row['version'],
                               row['effective_from'], row['effective_to'], bool(row['is_active']),
                               path, text, pages))
    return policies


def applicable(p: Policy, on: date) -> bool:
    day = on.isoformat()
    return p.effective_from <= day and (p.effective_to is None or day <= p.effective_to)


def policy_status(policies: List[Policy], on: date) -> Tuple[List[Policy], List[str]]:
    current = [p for p in policies if applicable(p, on)]
    warnings = []
    titles = {p.title for p in policies}
    for title in titles:
        matches = [p for p in current if p.title == title]
        if len(matches) > 1:
            warnings.append(f'CONFLICT: {title} has overlapping effective policy versions: ' +
                            ', '.join(f'{p.version} ({p.effective_from} to {p.effective_to or "open"})' for p in matches))
        if not matches:
            warnings.append(f'No policy effective on {on.isoformat()} for {title}.')
        for p in matches:
            if not p.is_active:
                warnings.append(f'Policy {title} v{p.version} is effective on {on} but marked inactive.')
    return current, warnings
