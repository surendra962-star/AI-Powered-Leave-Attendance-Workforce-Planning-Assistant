# AI-Powered Leave, Attendance & Workforce Planning Assistant

## Project Title and Overview

The **AI-Powered Leave, Attendance & Workforce Planning Assistant** is a local HR demonstration application for employees, managers, and HR administrators. It combines deterministic HR business rules with a grounded policy assistant.

The application supports leave requests and decisions, attendance regularization, comp-off tracking, team coverage planning, policy questions, dashboards, audit records, and CSV reporting. Python and SQLite perform the operational calculations; the language model only summarizes retrieved policy evidence and never approves leave or makes attendance decisions.

## Main Features

- **Leave management:** Apply, cancel, and review leave requests; validate notice and overlaps; calculate working days; track balances and approval deadlines.
- **Attendance:** Record clock-in and clock-out times, view attendance history, regularize missing punches, and calculate monthly summaries.
- **Comp-off:** Record earned and used comp-off days, track validity dates, and report expired or available balances.
- **Workforce planning:** Analyze team coverage, rank backup candidates, assess deadlines and capacity, and surface timeline alerts.
- **Policy assistant:** Retrieve policies by effective date, cite exact source versions, identify conflicts, and abstain from unsupported answers.
- **Dashboards:** Provide role-specific views for employees, managers, and HR, including metrics and operational risks.
- **Reporting and audit:** Export dashboard data and maintain leave decision, access, and system audit trails.

## User Roles

| Role | Main capabilities |
|---|---|
| Employee | View personal attendance, leave balances, leave requests, comp-off, deadlines, and team-relevant information; submit and cancel eligible leave requests; ask policy questions. |
| Manager | Perform employee capabilities plus review team leave requests, approve or decline requests, view team coverage and backups, regularize team attendance, and manage team timelines. |
| HR | Administer employees and HR records, view organization-wide dashboards and audit logs, review workforce information, and oversee the demo system. |

Managers and HR are the human decision-makers. Recommendations, coverage calculations, and policy retrieval do not make autonomous approval decisions.

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | Streamlit |
| REST API | Flask |
| Programming language | Python |
| Relational data | SQLite |
| Vector policy retrieval | ChromaDB |
| Embedding model | Sentence Transformers `all-MiniLM-L6-v2` |
| Optional local answer generation | Ollama with `llama3.2` |
| Policy files | Markdown and PDF through pypdf |
| Analytics and reporting | Pandas |
| Authentication | Salted PBKDF2-HMAC-SHA256 |
| Testing | pytest |

## Architecture

```text
Employee / Manager / HR
          |
          v
+----------------------+
| Streamlit UI         |
| app.py               |
+----------+-----------+
           |
           | Flask HTTP/JSON or direct-service fallback
           v
+----------------------+
| Flask REST API       |
| api.py / api_client.py|
+----------+-----------+
           |
           v
+----------------------+
| Python Services      |
| Access control       |
| Leave management     |
| Attendance           |
| Workforce planning   |
| Dashboards / analytics |
| Timeline / audit     |
+----------+-----------+
           |                         +-------------------------+
           v                         | Policy documents       |
+----------------------+             | PDF / Markdown files   |
| SQLite database      |             +-----------+-------------+
| hr_assistant.db      |                         |
+----------------------+                         v
                                      +-------------------------+
                                      | Sentence Transformers   |
                                      | ChromaDB retrieval      |
                                      | Effective-date routing  |
                                      | Optional Ollama answer  |
                                      +-------------------------+
```

## Requirements

- macOS, Linux, or Windows
- Python 3.9 or newer; final local verification used Python 3.13.9
- Python dependencies listed in [requirements.txt](requirements.txt)
- Optional Ollama installation for generated natural-language answers
- Internet access may be needed on first use to obtain the embedding model; subsequent retrieval depends on the local ChromaDB index

Install all Python dependencies with:

```bash
python -m pip install -r requirements.txt
```

Optional Ollama setup:

```bash
ollama serve
ollama pull llama3.2
```

If Ollama is unavailable, the policy assistant returns retrieved policy excerpts and citations.

## Setup Instructions

From the project root:

Use a project virtual environment so dependencies remain isolated from the system Python.
The `.venv/` directory is local-only and is excluded from GitHub.

You may keep `.venv/` on your computer while developing and running the project. Before
pushing to GitHub, do not add or commit it. It is intentionally excluded by `.gitignore`,
so Git should not include it. Anyone downloading the repository can recreate the same
environment using the setup commands below.

### macOS or Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m database.seed
python rag_cli.py index
python verify.py
```

After activation, verify that Flask belongs to the virtual environment and then start the API:

```bash
which python
python -c "import sys, flask; print(sys.executable); print(flask.__version__)"
python api.py
```

If `ModuleNotFoundError: No module named 'flask'` appears, do not launch the API first:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python api.py
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m database.seed
python rag_cli.py index
python verify.py
```

The initialized database is stored at `data/hr_assistant.db`. The generated policy vector index is stored at `data/chroma/`.
Both locations are runtime artifacts and are not intended for GitHub.
Recreate the database with `python -m database.seed` and rebuild the policy index with `python rag_cli.py index`.

## Timeline and Reminders

Timeline events are calculated and persisted for approval deadlines, project deadlines,
return-to-work dates, notice deadlines, and other operational items. Alerts are exposed
in the Streamlit **Timeline & Alerts** section and as a global alert banner for the active
employee, manager, or HR user. Alerts consider the configured horizon and show only events
within scope.

This demonstration provides **in-app reminders only**. It does not send email, SMS, or push
notifications. Generated alerts disappear from active reminder views only through their
persisted timeline status and date rules; they are not browser notifications.

## Evaluation Evidence

- The complete pytest suite and its collected/pass/fail/skip counts are recorded in
  [EVALUATION_REPORT.md](EVALUATION_REPORT.md).
- The report summarizes expected and actual outcomes for the assessment's required
  functional and RAG evaluation cases.

Important RAG behavior:
- Manager review timeline: **3 business days**.
- Deterministic policy facts are extracted before calling Ollama, where possible.
- Unsupported questions abstain instead of inventing a policy.
- Historical versions and current dates are routed by effective date.
- Conflicting policy versions are surfaced instead of silently selected.
- Every answer includes source markers and page/document citations.

## Narrated Demo

The repository does not contain a recorded video or audio file. Before external submission,
record a 5–10 minute narrated demonstration showing:

1. Employee login and policy citation.
2. Leave request, working days, balance, holiday, overlap, and comp-off behavior.
3. Coverage recommendation, deadline/backup conflict, and manager review.
4. Historical policy routing and unsupported-question abstention.
5. Manager/HR dashboards, analytics, timeline alerts, CSV export, and audit logs.

Upload the recording to an evaluator-accessible private location and add the recording
link to this section; do not embed real credentials or real employee information.

## Run Instructions

Start Flask first in one terminal:

```bash
source .venv/bin/activate
python api.py
```

Flask local URL: <http://127.0.0.1:5001>

Verify it:

```bash
curl http://127.0.0.1:5001/api/health
```

Start Streamlit in a second terminal:

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

Streamlit local URL: <http://localhost:8501>

Streamlit uses Flask when it is available and can fall back to direct Python services for the local demo.

## Demo Data

This project contains only fictional employees, teams, leave balances, attendance, policies, deadlines, comp-off records, and audit records. The seed includes two teams, sample HR/business records, historical policy versions, and three demo policy documents.

Synthetic comp-off credits are also seeded for demo use:

| Employee | Employee ID | Available comp-off |
|---|---|---|
| Rahul | `E001` | 2.0 days |
| Ravi | `E006` | 1.5 days |

`python -m database.seed` updates an existing database without duplicating
these labeled credits. Use `python -m database.seed --force` only as a demo reset.

> **DEMO ONLY:** The credentials below use synthetic accounts and passwords for local evaluation. Never reuse these passwords or expose this dataset outside a controlled demonstration environment.

| Role | Employee ID | Password |
|---|---|---|
| HR administrator | `HR001` | `hradmin@2026` |
| Engineering manager | `E005` | `kiranmgr@2026` |
| Employee | `E001` | `rahuluser@2026` |
| Product manager | `E010` | `vikrammgr@2026` |
| Product analyst | `E006` | `raviuser@2026` |

Initialize or update the synthetic dataset without dropping existing tables:

```bash
python -m database.seed
```

Reset and recreate the synthetic demo database:

```bash
python -m database.seed --force
python verify.py
python rag_cli.py index
```

The `--force` option recreates demo tables in the configured database. Do not run it against a real HR database.

## Synthetic Dataset and Database Schema

The repeatable seed creates fictional employees in two teams, employee/manager/HR
roles, annual and sick leave balances, public and optional holidays, leave
requests, attendance, comp-off records, project deadlines, backups, audit
records, and policy-document metadata. Policy source files are under
`data/policies/`. No real employee data or confidential company policy is used.

The main SQLite tables are:

| Tables | Purpose |
|---|---|
| `teams`, `employees`, `user_credentials` | Team coverage thresholds, role/team relationships, and salted password hashes |
| `leave_balances`, `leave_requests`, `decision_history` | Entitlements, requests and statuses, human decisions, and recommendation evidence |
| `holidays`, `attendance`, `comp_off_records` | Calendar rules, daily attendance, and earned/used/expired comp-off |
| `project_deadlines`, `backup_assignments`, `timeline_items` | Delivery risks, designated backups, and persistent timeline events |
| `policy_documents` | Policy versions, effective dates, and source paths |
| `audit_logs` | Auditable actor, action, target, and timestamp records |

`database/schema.sql` defines the relational schema, constraints, and indexes.
The SQLite database and Chroma index are generated locally and excluded from
the repository; run the seed and index commands above to recreate them.

## RAG, Rules, and Metric Definitions

Markdown and PDF policies are loaded with their version and effective-date
metadata. `rag/chunks.py` splits text at headings and paragraphs into chunks of
up to 950 characters. Sentence Transformers creates normalized embeddings;
ChromaDB uses cosine distance and searches only policies applicable on the
requested date. The assistant considers the four closest results, rejects
weak matches above a 0.70 distance, and cites the matching document, version,
section, page, and file. Ollama may phrase supported evidence; it does not
calculate balances or make HR decisions. Conflicting versions are surfaced,
and insufficient evidence produces an abstention.

Operational rules are deterministic and covered by pytest:

- **Working days:** Monday-Friday dates, excluding public holidays. Optional
  holidays are excluded only when the employee elects to use one.
- **Annual/sick balance:** remaining days = entitlement minus used days;
  available days further subtract pending and review-required requests.
- **Attendance percentage:** present days / (present days + absent days) * 100.
  Approved leave is excluded from the denominator.
- **Team coverage:** available active team members / total active team members
  * 100. Approved, pending, or review-required leave counts as an absence on a
  working day. Weekends and public holidays are non-working days.
- **Comp-off:** only available, unexpired credits can be used; used and expired
  credits do not contribute to available balance.

Human managers or HR make final leave decisions. Coverage and backup results
are recommendations for review, not automatic approvals.

## Testing

Run the complete pytest suite from the project root:

```bash
python -m pytest -q
```

Focused suites are also available:

```bash
python -m pytest -v tests/test_phase1_access_control.py
python -m pytest -v tests/test_phase3_complete.py
python -m pytest -v tests/test_phase4_complete.py
python -m pytest -v tests/test_phase5_complete.py
python -m pytest -v tests/test_api_flask.py
python -m pytest -v tests/test_rag_10_benchmark_questions.py
python -m pytest -v tests/test_end_to_end_scenarios.py
```

The test suite covers database access, role boundaries, leave, attendance,
workforce planning, dashboards, Flask API routes, RAG behavior, and end-to-end scenarios.

## Privacy and Limitations

- All employees, credentials, leave records, policies, attendance data, deadlines, and audit information are synthetic.
- The policy documents are demo samples, not legal or employment advice, and may not reflect any jurisdiction's real requirements.
- This is a single-host demonstration, not a production HR system.
- SQLite, process-local login tokens, and local service fallback are suitable for local testing but require production database, session, backup, and scaling designs.
- No HTTPS, secrets manager, distributed access control, brute-force protection, monitoring, or disaster recovery is configured.
- Real employee data would require suitable privacy, retention, minimization, access review, encryption, and breach procedures.
- Policy answers depend on the quality and scope of the indexed documents; the assistant may abstain when evidence is insufficient.
- Managers and HR retain final authority for leave and HR decisions.

## Repository Contents

```text
ai_hr/
├── app.py                 # Streamlit user interface
├── api.py                 # Flask REST API
├── api_client.py          # API client and direct-service fallback
├── config.py              # Shared application settings
├── rag_cli.py             # Policy indexing and command-line questions
├── verify.py              # Database verification summary
├── requirements.txt       # Python dependencies
├── README.md              # Project overview and operating instructions
├── access_control/        # Authentication, RBAC, sessions, and audit scope
├── attendance/            # Clock-in/out and attendance regularization
├── dashboards/            # Employee, manager, and HR views
├── analytics/             # Workforce and dashboard metrics
├── database/              # SQLite initialization and synthetic seeding
├── leave_management/      # Leave calculations, balances, requests, and decisions
├── workforce_planning/    # Coverage, backups, capacity, and deadlines
├── timeline/              # Timeline events and operational alerts
├── rag/                   # Policy ingestion, embeddings, retrieval, and grounding
├── data/
│   ├── hr_assistant.db    # Runtime SQLite database
│   ├── policies/          # Synthetic Markdown and PDF policies
│   ├── rag_benchmark_questions.json
│   └── chroma/            # Generated ChromaDB vector index
└── tests/                 # pytest unit, API, security, integration, and benchmark suites
```
