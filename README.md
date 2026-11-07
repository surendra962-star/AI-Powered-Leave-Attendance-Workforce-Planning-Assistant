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
The Flask backend runs on `http://localhost:5000` and provides complete REST endpoints:
- **Authentication**: `POST /api/auth/login`
- **Leave Operations**: `POST /api/leave/request`, `GET /api/leave/balance`, `GET /api/leave/requests`, `POST /api/leave/decide`, `POST /api/leave/cancel`, `GET /api/leave/holidays`, `GET /api/leave/decision-history/<id>`
- **Attendance**: `POST /api/attendance/clock-in`, `POST /api/attendance/clock-out`, `GET /api/attendance/history`, `GET /api/attendance/missing-clock-outs`, `POST /api/attendance/regularize`
- **Workforce Planning**: `POST /api/workforce/evaluate`, `GET /api/workforce/coverage`, `GET /api/workforce/backups`, `POST /api/workforce/what-if`
- **Dashboards**: `GET /api/dashboard/employee`, `GET /api/dashboard/manager`, `GET /api/dashboard/hr`
- **Timeline & Alerts**: `GET /api/timeline/alerts`, `GET /api/timeline/events`, `GET /api/compoff/summary`, `POST /api/timeline/query-overlap`
- **Workforce Analytics**: `GET /api/analytics/metrics`, `GET /api/analytics/team-coverage`, `GET /api/analytics/organization`
- **RAG Policy Assistant**: `POST /api/rag/ask`, `POST /api/rag/reindex`
- **Governance & Audit**: `GET /api/admin/employees`, `GET /api/admin/audit-logs`

### 7. Launch the Streamlit Frontend Application
Start the interactive UI:

```bash
python -m streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 🧪 Comprehensive Test Suite Execution

Execute the full suite of **145 automated unit, integration, and scenario tests** (100% passing across all 15 test modules):

```bash
# Run the complete test suite
python -m pytest -v

# Run specific test modules
python -m pytest -v tests/test_phase5_complete.py
python -m pytest -v tests/test_phase4_complete.py
python -m pytest -v tests/test_phase3_complete.py
python -m pytest -v tests/test_end_to_end_scenarios.py
python -m pytest -v tests/test_rag_phase2.py
python -m pytest -v tests/test_attendance.py
python -m pytest -v tests/test_audit_and_admin.py
python -m pytest -v tests/test_phase4_workforce_planning.py
```

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
