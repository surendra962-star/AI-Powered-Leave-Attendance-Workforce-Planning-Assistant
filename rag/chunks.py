from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional
from rag.policies import Policy

@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    policy_id: int
    title: str
    version: str
    section: str
    effective_from: str
    effective_to: str
    is_active: bool
    source: str
    page: Optional[int] = None


def split_policy(policy: Policy, max_chars: int = 950) -> List[Chunk]:
    if max_chars < 150:
        raise ValueError('max_chars must be at least 150')
    pages = policy.pages or [(1, policy.text)]
    chunks = []
    current_heading = 'Introduction'

    for page_num, page_text in pages:
        sections = []
        heading, buffer = current_heading, []
        for line in page_text.splitlines():
            if re.match(r'^#{1,3}\s+', line):
                if buffer and '\n'.join(buffer).strip():
                    sections.append((heading, '\n'.join(buffer).strip()))
                heading, buffer = line.lstrip('#').strip(), []
                current_heading = heading
            else:
                buffer.append(line)
        if buffer and '\n'.join(buffer).strip():
            sections.append((heading, '\n'.join(buffer).strip()))

        for sec_heading, body in sections:
            # split overlong paragraphs without dropping content
            units = []
            for paragraph in re.split(r'\n\s*\n', body):
                while len(paragraph) > max_chars:
                    cut = paragraph.rfind(' ', 0, max_chars)
                    cut = cut if cut > 0 else max_chars
                    units.append(paragraph[:cut].strip())
                    paragraph = paragraph[cut:].strip()
                if paragraph:
                    units.append(paragraph)
            pieces, part = [], ''
            for unit in units:
                if part and len(part) + len(unit) + 2 > max_chars:
                    pieces.append(part)
                    part = ''
                part = (part + '\n\n' + unit).strip()
            if part:
                pieces.append(part)
            for index, piece in enumerate(pieces):
                content = f'Policy: {policy.title} v{policy.version}\nSection: {sec_heading}\n{piece}'
                key = f'{policy.policy_id}|{page_num}|{sec_heading}|{index}|{content}' if len(pages) > 1 else f'{policy.policy_id}|{sec_heading}|{index}|{content}'
                chunk_id = hashlib.sha256(key.encode()).hexdigest()[:24]
                chunks.append(Chunk(chunk_id, content, policy.policy_id, policy.title,
                                    policy.version, sec_heading, policy.effective_from,
                                    policy.effective_to or '', policy.is_active,
                                    str(policy.path.name), page=page_num))
    return chunks
