# AI-Powered Leave, Attendance & Workforce Planning Assistant

A comprehensive, production-grade AI-powered HR Assistant built on Python 3.9, SQLite, ChromaDB, local Ollama LLMs, and Streamlit. The application strictly adheres to the principle of **human-in-the-loop decision authority**: all leave calculations, balances, working days, attendance, and workforce coverage metrics are determined deterministically, while the AI RAG assistant provides fully grounded, cited answers to HR policy questions without autonomous decision-making.

---

## 🏛️ System Architecture

```text
                                 [ User / Examiner ]
                                          │
                                          ▼
                       [ Streamlit Web Application (app.py) ]
                                          │
                 ┌────────────────────────┴────────────────────────┐
                 ▼                                                 ▼
      [ Authentication & RBAC ]                         [ HR Policy RAG Assistant ]
      (PBKDF2 Salted Hashes,                            (Semantic + Keyword Retrieval,
       UserContext Session Guard)                        ChromaDB Vector Store)
                 │                                                 │
                 ▼                                                 ▼
      [ Core Backend Services ]                         [ Local Ollama Inference ]
      ├── Leave Management (Working Days, Overlaps)      (Llama 3.2 Local LLM,
      ├── Attendance (Clock-In/Out, Monthly %, CSV)      Grounded Citations & Abstention)
      ├── Comp-off & Holiday Tracking
      ├── Workforce Planning & Backup Identification
      ├── Timeline, Deadlines & In-App Alerts
      └── Workforce Analytics (Pandas + Aggregations)
                 │
                 ▼
       [ SQLite Database (hr_assistant.db) ]
       (Foreign Keys, ACID Transactions, Indexes, Audit Logs)
```

### Core Architectural Separations
1. **Deterministic Business Logic**: All working day calculations (excluding weekends and public holidays), notice periods, leave overlap checks, balance deductions, attendance percentages, and team coverage thresholds are computed deterministically in pure Python and SQLite.
2. **RAG Policy Retrieval**: HR policy documents (PDF and Markdown) are chunked, embedded with `sentence-transformers`, stored persistently in ChromaDB, and retrieved with strict semantic similarity thresholds.
3. **LLM Response Generation**: The local Ollama LLM (`llama3.2`) answers strictly from retrieved context and cites document titles, versions, sections, and page numbers. It explicitly abstains on unsupported or unanswerable queries without hallucinating policy rules.
4. **Human Decision Authority**: The assistant never autonomously approves or declines leave requests. Managers and HR personnel retain sole authority over final decisions.

## 🛠️ Technology Stack Specification

The implementation strictly satisfies the specified architecture layers:

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend** | Streamlit | Employee, Manager and HR dashboards |
| **Backend** | Flask | REST APIs and request handling |
| **Business logic** | Python | Leave, attendance and workforce rules |
| **Relational database** | SQLite | Employee and HR records |
| **Vector database** | ChromaDB | HR policy embeddings |
| **Embedding model** | Sentence Transformers | Convert policy text into vectors |
| **LLM** | Ollama – Llama 3.2 | Generate policy-based answers |
| **PDF processing** | pypdf | Extract policy documents |
| **Data processing** | Pandas | HR analytics |
| **Testing** | Pytest | Unit and integration tests |

---

## 🔑 Pre-Seeded Assessment Accounts & Credentials

The application includes synthetic employees across three distinct roles with pre-configured credentials:

| Role | Employee ID | Name | Team | Email | Password |
|---|---|---|---|---|---|
| **HR Administrator** | `HR001` | HR Admin | T01 | `hr.admin@company.test` | `hradmin@2026` |
| **Engineering Manager** | `E005` | Kiran Rao | T01 | `kiran.rao@company.test` | `kiranmgr@2026` |
| **Senior AI Engineer** | `E001` | Rahul Sharma | T01 | `rahul.sharma@company.test` | `rahuluser@2026` |
| **Product Manager** | `E010` | Vikram Malhotra | T02 | `vikram.malhotra@company.test` | `vikrammgr@2026` |
| **Product Analyst** | `E006` | Ravi Kumar | T02 | `ravi.kumar@company.test` | `raviuser@2026` |

*Passwords are hashed using salted cryptographic digests stored in the `user_credentials` table.*

---

## 🚀 Quickstart & Setup Guide

### 1. Environment Activation
The project is strictly compatible with **Python 3.9**. Use the existing virtual environment:

```bash
# Activate the virtual environment
source .venv/bin/activate

# Verify Python version (must be 3.9.x)
python --version
```

### 2. Dependency Verification
Install dependencies using the virtual environment interpreter:

```bash
python -m pip install -r requirements.txt
```

### 3. Database Initialization & Seeding
Initialize the SQLite schema, create tables, migrate indexes, and seed synthetic records:

```bash
# Seed teams, employees, balances, holidays, deadlines, and credentials
python -m database.seed

# Verify table row counts
python verify.py
```

### 4. Policy Document Indexing (ChromaDB)
Rebuild the local vector index from registered HR policy documents (PDF and Markdown):

```bash
python rag_cli.py index
```

### 5. Local Ollama LLM Setup (Optional for Live RAG)
Install and run local Ollama with `llama3.2`:

```bash# Start Ollama service (in a separate terminal)
ollama serve

# Pull the lightweight 3.2 model
ollama pull llama3.2
```
*Note: If Ollama is not running, the application gracefully provides retrieved excerpts and citations.*

### 6. Launch the Flask Backend API (REST Service)
Start the REST API server:

```bash
python api.py
```
The Flask backend runs on `http://localhost:5000` and provides 24 production-grade REST endpoints with PBKDF2 authentication, token-based user context verification, and role-based access control (`401 Unauthorized`, `403 Forbidden`, `400 Bad Request`):

| Category | Endpoint | Method | Role | Description |
|---|---|---|---|---|
| **Auth** | `/api/auth/login` | POST | Public | Authenticates employee/manager/HR, returns session credentials |
| **Auth** | `/api/auth/me` | GET | Authenticated | Returns current authenticated user context |
| **Leave** | `/api/leave/request` | POST | Authenticated | Creates a new leave request with deterministic validation |
| **Leave** | `/api/leave/balance` | GET | Authenticated | Retrieves entitled, used, pending, and remaining balances |
| **Leave** | `/api/leave/requests` | GET | Authenticated | Lists leave requests filtered by status or employee |
| **Leave** | `/api/leave/decide` | POST | Manager/HR | Human manager decision with review note |
| **Leave** | `/api/leave/cancel` | POST | Authenticated | Cancels pending or active leave, restoring balances |
| **Leave** | `/api/leave/holidays` | GET | Authenticated | Retrieves public and optional holiday calendar |
| **Leave** | `/api/leave/decision-history/<id>` | GET | Authenticated | Retrieves full chronological audit trail of AI & human actions |
| **Attendance** | `/api/attendance/clock-in` | POST | Authenticated | Logs daily clock-in; prevents duplicate check-ins |
| **Attendance** | `/api/attendance/clock-out` | POST | Authenticated | Logs daily clock-out and updates duration |
| **Attendance** | `/api/attendance/history` | GET | Authenticated | Retrieves employee attendance logs |
| **Attendance** | `/api/attendance/missing-clock-outs` | GET | Authenticated | Discovers unclosed check-in sessions |
| **Attendance** | `/api/attendance/regularize` | POST | Authenticated | Regularizes missing punch records with audit logging |
| **Workforce** | `/api/workforce/evaluate` | POST | Manager/HR | Evaluates workforce coverage and recommendation for a request |
| **Workforce** | `/api/workforce/coverage` | GET | Manager/HR | Returns team daily staffing levels and breach flags |
| **Workforce** | `/api/workforce/backups` | GET | Manager/HR | Recommends ranked backup team candidates |
| **Workforce** | `/api/workforce/what-if` | POST | Manager/HR | Simulates hypothetical leave scenarios with custom thresholds |
| **Dashboards** | `/api/dashboard/employee` | GET | Authenticated | Self-scoped dashboard for personal metrics & balances |
| **Dashboards** | `/api/dashboard/manager` | GET | Manager/HR | Team-scoped dashboard for staffing, pending SLA, & alerts |
| **Dashboards** | `/api/dashboard/hr` | GET | HR Admin | Org-wide dashboard for metrics, compliance, & directories |
| **Timeline** | `/api/timeline/alerts` | GET | Authenticated | Surfaces overdue items, approval deadlines, & low coverage |
| **Timeline** | `/api/timeline/events` | GET | Authenticated | Retrieves chronological timeline items |
| **Timeline** | `/api/timeline/query-overlap` | POST | Authenticated | Evaluates proposed leave window against deliverables & milestones |
| **Comp-off** | `/api/compoff/summary` | GET | Authenticated | Returns earned, used, available, pending, & expiring credits |
| **Analytics** | `/api/analytics/metrics` | GET | Authenticated | Multi-dimensional metrics (team, employee, month, type, status) |
| **Analytics** | `/api/analytics/team-coverage` | GET | Manager/HR | Longitudinal daily coverage % and breach diagnostics |
| **Analytics** | `/api/analytics/organization` | GET | HR Admin | Company-wide workforce breakdown and headcount summary |
| **Analytics** | `/api/analytics/export-csv` | GET | Authenticated | Exports workforce analytics data as CSV |
| **RAG** | `/api/rag/ask` | POST | Authenticated | Grounded policy Q&A with multi-page citations & abstention |
| **RAG** | `/api/rag/reindex` | POST | HR Admin | Rebuilds ChromaDB vector index from registered policy files |
| **Admin** | `/api/admin/employees` | GET | HR Admin | Lists all active and inactive employees |
| **Admin** | `/api/admin/create-employee` | POST | HR Admin | Provisions new employee profile with credentials |
| **Admin** | `/api/admin/deactivate-employee` | POST | HR Admin | Deactivates employee profile |
| **Admin** | `/api/admin/audit-logs` | GET | HR Admin | Retrieves immutable system audit trail |

#### Quick API Testing with cURL

```bash
# 1. Authenticate as Rahul Sharma (Senior AI Engineer)
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"employee_id": "E001", "password": "rahuluser@2026"}'

# 2. Check personal leave balances
curl -X GET "http://localhost:5000/api/leave/balance?employee_id=E001" \
  -H "X-Employee-ID: E001" -H "X-Employee-Role: employee" -H "X-Employee-Team: T01"

# 3. Clock-in for the day
curl -X POST http://localhost:5000/api/attendance/clock-in \
  -H "Content-Type: application/json" \
  -H "X-Employee-ID: E001" -H "X-Employee-Role: employee" -H "X-Employee-Team: T01" \
  -d '{"notes": "WFH Remote Session"}'

# 4. Ask RAG Policy Assistant
curl -X POST http://localhost:5000/api/rag/ask \
  -H "Content-Type: application/json" \
  -H "X-Employee-ID: E001" -H "X-Employee-Role: employee" -H "X-Employee-Team: T01" \
  -d '{"question": "How many days of annual leave do I get?", "as_of_date": "2026-03-01"}'

# 5. Verify RBAC Security (Employee blocked from HR Audit Logs -> 403 Forbidden)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/api/admin/audit-logs \
  -H "X-Employee-ID: E001" -H "X-Employee-Role: employee" -H "X-Employee-Team: T01"
# Output: 403
```

### 7. Launch the Streamlit Frontend Application (Dual-Mode Execution)
Start the interactive UI:

```bash
python -m streamlit run app.py
```
Open your browser at `http://localhost:8501`.

**Dual-Mode Operation**:
- When the Flask backend is running on `http://localhost:5000`, Streamlit routes API actions (leave requests, clock-in/out, manager decisions, cancellations, analytics) through the Flask REST API. The UI sidebar displays a green **⚡ Connected to Flask API: http://localhost:5000** badge.
- If the Flask backend is offline or stopped, the frontend seamlessly switches to direct service execution via local fallback, ensuring high availability.

---

## 🧪 Comprehensive Test Suite Execution

Execute the full suite of **159 automated unit, integration, and scenario tests** (100% passing across all 16 test modules):

```bash
# Run the complete test suite
python -m pytest -v

# Run specific test modules
python -m pytest -v tests/test_rag_10_benchmark_questions.py # 10 Grounded Policy Scenarios & Edge Cases
python -m pytest -v tests/test_api_flask.py                 # 24 Flask REST Endpoints & RBAC Security
python -m pytest -v tests/test_end_to_end_scenarios.py       # 10 End-to-End Workflow Scenarios
python -m pytest -v tests/test_phase5_complete.py            # Analytics & Dashboards Suite
python -m pytest -v tests/test_phase4_complete.py            # Attendance, Comp-off & Workforce Planning
python -m pytest -v tests/test_phase3_complete.py            # Leave Management & Decision Support
python -m pytest -v tests/test_rag_phase2.py                 # ChromaDB, Citations & Prompt Injection
python -m pytest -v tests/test_attendance.py                 # Clock-in/out & Missing Punches
python -m pytest -v tests/test_audit_and_admin.py            # RBAC Isolation & Immutable Audit Logs
```

### 📋 The 10 Benchmark Policy RAG Suite (`data/rag_benchmark_questions.json`)
The assessment includes a structured benchmark suite testing complex real-world HR policy inquiries:
1. **Annual Leave Entitlement**: Verified against Sample Leave Policy v2.0 (Page 1) -> 18 days.
2. **Advance Notice Requirement**: Verified against Sample Leave Policy v2.0 (Page 1) -> 5 calendar days.
3. **Sick Leave & Medical Certificate**: Multi-page citation verified on Page 2 -> $\ge 3$ consecutive days requires doctor's note.
4. **Comp-off Earning & Validity**: 60-day expiry rule grounded with exact section citations.
5. **Effective Date Routing (2025 vs 2026)**: Historical query (As-of `2025-10-01`) routes to Policy v1.0 (15 days), while modern query (`2026-03-01`) routes to Policy v2.0 (18 days).
6. **Probation Leave Eligibility**: Verified against Page 2 -> Sick leave only during first 3 months.
7. **Leave Cancellation Policy**: Grounded explanation of approval restoration rules.
8. **Prompt Injection Defense**: Evaluates resistance against malicious adversarial text attempting to grant infinite leave.
9. **Conflicting Policy Version Transparency**: Surfaces warning banners when overlapping or divergent rules exist across active policies.
10. **Out-of-Scope Safe Abstention**: Safely abstains on unmentioned rules (e.g., pet insurance, space travel) without hallucinating citations.

---

## 🌟 Bonus Features Implemented (PDF Section 11)

In addition to the core functional requirements, the project includes the following advanced bonus capabilities:

1. **What-If Analysis & Coverage Simulation**: Interactive simulation in `Manager Review` allowing managers to test hypothetical leave scenarios for multiple team members across arbitrary date windows.
2. **Explainable Coverage Score with Configurable Thresholds**: Dynamic threshold slider (10%–100%) providing instant feasibility scores, breach alerts, and deadline collision warnings.
3. **Multi-Model LLM Runtime**: Support for both `llama3.2` and `deepseek-r1` with an interactive switcher in the Streamlit UI and custom Ollama tag input.
4. **Policy Version Comparison with Effective-Date Handling**: Side-by-side comparison between 2025 v1.0 and 2026 v2.0 policy documents with date-bound query routing.
5. **System Audit Trail**: Real-time logging of manager decisions, leave approvals/declines, and policy changes stored in SQLite with actor and timestamp indexes.
6. **Data Export Suite**: One-click CSV exports for employee attendance history and organization-wide workforce metrics.

---

## 📚 Key Documentation References

- [INTERVIEW_ANSWERS.md](file:///Users/kummarisurendrakumar/Downloads/ai_hr/INTERVIEW_ANSWERS.md): Complete technical answers, architecture diagrams, and mathematical models for all 10 interview questions from Section 13 (Page 10) of the assignment PDF.
- [EVALUATION_REPORT.md](file:///Users/kummarisurendrakumar/Downloads/ai_hr/EVALUATION_REPORT.md): Comprehensive evaluation report with gap analysis, 10 assessment scenario verification matrix, and test logs.
- [DEMO_SCRIPT.md](file:///Users/kummarisurendrakumar/Downloads/ai_hr/DEMO_SCRIPT.md): Step-by-step 8–10 minute narrated walkthrough script for the examiner video demo.

---

## ⚖️ Boundaries & Ethical Considerations

- **Synthetic Data**: All employee records, names, emails, and attendance logs are entirely synthetic and fictional.
- **Attendance Context**: Missing attendance records are not automatically classified as misconduct or disciplinary absence.
- **Decision Authority**: AI recommendations are strictly advisory; managers and HR retain sole authority over final decisions.
- **Notifications**: In accordance with local assignment guidelines, alerts are rendered in-app; no external SMS/SMTP dependencies are claimed.
