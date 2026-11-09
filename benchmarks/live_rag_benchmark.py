"""Run the fixed policy benchmark against the real Chroma index and Ollama."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import EMBEDDING_MODEL, OLLAMA_MODEL, ROOT
from rag.assistant import ask
from rag.chunks import split_policy
from rag.policies import load_policies
from rag.store import embedder, rebuild, search


QUESTIONS = ROOT / "data" / "rag_benchmark_questions.json"
INDEX_DIR = ROOT / "data" / "chroma"
REPORT = ROOT / "LIVE_RAG_BENCHMARK_RESULTS.md"


def main() -> None:
    policies = load_policies()
    chunks = [chunk for policy in policies for chunk in split_policy(policy)]
    model = embedder(EMBEDDING_MODEL)
    chunk_count = rebuild(chunks, INDEX_DIR, model=model)

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    rows = []
    failures = []

    try:
        import ollama
        ollama.list()
        ollama.chat(model=OLLAMA_MODEL, messages=[
            {"role": "user", "content": "Reply with the single word OK."}
        ])
        model_available = True
    except Exception as exc:
        model_available = False
        model_error = str(exc)

    for item in questions:
        as_of = date.fromisoformat(item["as_of"])
        from rag.policies import policy_status
        active, warnings = policy_status(policies, as_of)
        hits = search(item["question"], INDEX_DIR, model=model, policy_ids=[p.policy_id for p in active])
        evidence = [hit for hit in hits if hit["distance"] <= 0.70]
        result = ask(
            item["question"],
            on=as_of,
            index_dir=INDEX_DIR,
            model=model,
            llm_model=OLLAMA_MODEL,
        )
        answer = result["answer"].lower()
        expected_keywords = item["expected_keywords"]
        answer_keywords = sum(1 for keyword in expected_keywords if keyword.lower() in answer)
        retrieved_sources = [
            {
                "document": hit["metadata"].get("title"),
                "version": hit["metadata"].get("version"),
                "section": hit["metadata"].get("section"),
                "page": hit["metadata"].get("page"),
                "distance": round(hit["distance"], 4),
            }
            for hit in evidence[:4]
        ]
        retrieved_expected = bool(
            evidence
            and not item["should_abstain"]
            and any(
                hit["metadata"].get("title") == item["expected_document"]
                and str(hit["metadata"].get("version")) == item["expected_version"]
                and hit["metadata"].get("section") == item["expected_section"]
                and int(hit["metadata"].get("page", 1)) == item["expected_page"]
                for hit in evidence
            )
        )
        supported = not item["should_abstain"] and answer_keywords == len(expected_keywords)
        if item["should_abstain"]:
            supported = (
                "does not specify" in answer
                or "do not specify" in answer
                or "not available" in answer
                or "abstain" in answer
            )
        passed = supported and (item["should_abstain"] or retrieved_expected or bool(evidence))
        if not model_available:
            passed = False
        row = {
            "id": item["id"],
            "category": item["category"],
            "expected_retrieval": retrieved_expected,
            "evidence_count": len(evidence),
            "answer_supported": supported,
            "passed": passed,
            "retrieved_sources": retrieved_sources,
        }
        rows.append(row)
        if not passed:
            failures.append(row)

    lines = [
        "# Live Policy RAG Benchmark",
        "",
        f"- Run timestamp: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Embedding model: `{EMBEDDING_MODEL}`",
        f"- Generation model: `{OLLAMA_MODEL}`",
        f"- Ollama available: `{model_available}`",
        f"- Live generation check: `{'PASS' if model_available else 'FAIL/UNAVAILABLE'}`",
        f"- Indexed chunks: `{chunk_count}`",
        f"- Fixed benchmark cases: `{len(rows)}`",
        "",
        "| ID | Category | Retrieval | Evidence | Answer Support | Result |",
        "|---|---|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['category']} | {'PASS' if row['expected_retrieval'] else ('N/A' if row['evidence_count'] == 0 else 'FAIL')} | "
            f"{row['evidence_count']} | {'PASS' if row['answer_supported'] else 'FAIL'} | {'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Retrieval Details",
        "",
    ])
    for row in rows:
        lines.append(f"### {row['id']}")
        if row["retrieved_sources"]:
            for source in row["retrieved_sources"]:
                lines.append(
                    "- "
                    + f"{source['document']} v{source['version']} — {source['section']} "
                    + f"(Page {source['page']}, distance {source['distance']})"
                )
        else:
            lines.append("- No evidence passed the configured distance threshold.")

    if not model_available:
        lines.extend(["", "## Model Availability", "", f"Live Ollama generation was unavailable: `{model_error}`"])

    passed_count = sum(1 for row in rows if row["passed"])
    lines.insert(6, f"- Passed cases: `{passed_count}/{len(rows)}`")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT.relative_to(ROOT)}: {passed_count}/{len(rows)} passed")
    for row in failures:
        print("FAIL", row["id"], row["category"])


if __name__ == "__main__":
    main()
