# Live Demonstration & Evaluation Script
## AI-Powered Leave, Attendance & Workforce Planning Assistant

**Target Presentation Time**: 8–10 Minutes  
**Prerequisites**:
1. Activate environment: `source .venv/bin/activate`
2. Start Flask REST API backend: `python api.py` (Runs on `http://localhost:5001`)
3. Start Streamlit frontend: `python -m streamlit run app.py` (Opens `http://localhost:8501`)

---

### Step 1: Architectural Overview & Role Boundaries (1 Minute)
- **Objective**: Explain the strict boundary between AI policy reasoning and deterministic business rules.
- **Narrative**:
  - *"Our system solves the HR automation challenge by strictly separating grounded knowledge retrieval from mission-critical business logic."*
  - *"Deterministic algorithms compute working days (excluding weekends and public holidays), balance deductions, duplicate requests, attendance percentages, and workforce coverage in pure Python and SQLite."*
  - *"The RAG assistant retrieves company policies from ChromaDB and uses local Ollama (`llama3.2`) to answer policy inquiries with verifiable multi-page and section citations."*
  - *"Crucially, the AI assistant never makes autonomous approval or rejection decisions (`automatic_approval = False`). Human managers and HR retain sole decision-making authority."*
  - *"The architecture features dual-mode execution: a 24-endpoint Flask REST backend on port 5000 coupled with an interactive Streamlit frontend on port 8501 with resilient local fallback."*

---

### Step 2: Flask REST API & RBAC Verification (1 Minute)
- **Objective**: Demonstrate that core HR services are exposed via a clean, secured REST API.
- **Actions in Terminal**:
  ```bash
  # 1. Authenticate as Rahul Sharma (Senior AI Engineer)
  curl -s -X POST http://localhost:5001/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"employee_id": "E001", "password": "rahuluser@2026"}' | jq .

  # 2. Query personal leave balance via REST API
  curl -s -X GET "http://localhost:5001/api/leave/balance?employee_id=E001" \
    -H "X-Employee-ID: E001" -H "X-Employee-Role: employee" -H "X-Employee-Team: T01" | jq .

  # 3. Demonstrate RBAC Security Isolation (Employee blocked from HR Audit Logs -> 403 Forbidden)
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/api/admin/audit-logs \
    -H "X-Employee-ID: E001" -H "X-Employee-Role: employee" -H "X-Employee-Team: T01"
  # Terminal prints: 403
  ```
- **Narrative**:
  - *"The Flask API enforces role-based access control directly at the network boundary, returning 401 Unauthorized for unauthenticated requests and 403 Forbidden when an employee attempts administrative operations."*

---

### Step 3: Employee Workspace Demonstration (2 Minutes)
- **Login Credentials**: `E001` / `rahuluser@2026` (Rahul Sharma, Senior AI Engineer)
- **Actions in Streamlit**:
  1. **Dual-Mode Indicator**: Point out the green badge in the sidebar: `⚡ Connected to Flask API: http://localhost:5001`.
  2. **Personal Dashboard**: Inspect separate leave balances (Annual: entitled 18, used, pending, remaining, available), attendance summary, and comp-off credits.
  3. **Daily Clock-In**: In **Attendance Management**, click **🕒 Clock In Today**. Show that the punch timestamp is logged immediately. Demonstrate duplicate clock-in prevention by attempting to click it again (warning displayed).
  4. **Leave Application**: Navigate to **Apply for Leave**:
     - Select `annual` leave for `2026-12-07` to `2026-12-09`.
     - Show the **Duration Preview** automatically calculating **3 working days** (excluding weekends).
     - Submit request. Show confirmation: *"Submitted for human review. It has not been approved."*
  5. **Leave Cancellation**: Return to **My Dashboard**, expand *Cancel an Active or Pending Leave Request*, and cancel the submitted request. Show that balance remains intact.
  6. **Sign Out**: Click **🚪 Sign Out** in sidebar.

---

### Step 4: Manager Decision Support & Workforce Planning (2.5 Minutes)
- **Login Credentials**: `E005` / `kiranmgr@2026` (Kiran Rao, Engineering Manager)
- **Actions in Streamlit**:
  1. **Team Dashboard**: View team active headcount (6 active members in Team `T01`), minimum required coverage (60%), and pending requests.
  2. **Manager Review**: Select a pending leave request.
  3. **Evaluate Workforce Impact**: Click **🔍 Evaluate Workforce Impact & Coverage**:
     - Show deterministic daily coverage calculation.
     - Show whether team coverage drops below 60%.
     - Point out the explainable recommendation (`Likely eligible`, `Needs manager review`, or `Potential policy conflict`), rules evaluated, and missing information.
  4. **What-If Coverage Simulation**: In the Simulation expander, simulate concurrent leave for candidate team members across sprint dates to observe capacity impact.
  5. **Human Decision Recording**:
     - Emphasize the banner: *"AI Decision Support: Human retains final decision-making authority."*
     - Enter review note: *"Approved based on sprint deliverables."*
     - Click **Record Final Decision** as `approved`.
     - Show that the leave status updates, balances deduct atomically, and attendance is synchronized.
  6. **Critical Deadline & Backup Identification**:
     - Scroll to *Critical Deadlines & Backup Candidate Identification*.
     - Select project deadline (`Q4 Core AI Pipeline Delivery`).
     - Click **Identify Available Backup Candidates**. Show ranked team members with availability status.
  7. **Sign Out**.

---

### Step 5: HR Administration & Governance (1.5 Minutes)
- **Login Credentials**: `HR001` / `hradmin@2026` (HR Administrator)
- **Actions in Streamlit**:
  1. **Organization Overview**: View active headcount across all teams (`T01`, `T02`) and registered policy versions.
  2. **HR Employee Admin**:
     - Register a new employee (e.g. `E012`, `Ananya Sharma`, `T01`). Show immediate appearance in directory.
     - Demonstrate password updating for synthetic employees.
  3. **Daily Attendance Overview**: View organization-wide daily clock-in/out records and click **📥 Download Full Attendance CSV**.
  4. **System Audit Logs**: Open **System Audit Logs** to show the immutable audit trail capturing logins, employee creations, comp-off grants, and leave approvals.
  5. **Workforce Analytics**:
     - Inspect monthly attendance percentage formula (`Present / (Present + Absent) * 100`).
     - Show multi-dimensional filters (team, employee, month, leave type, status).
     - Click **📥 Export Workforce Metrics CSV**.

---

### Step 6: HR Policy Assistant RAG Demonstration (1.5 Minutes)
- **Navigation**: Open **HR Policy Assistant (RAG)**
- **10 Benchmark Questions Walkthrough**:
  1. **Annual Leave Entitlement**: Select *"How many annual leave days are provided per year?"*
     - Click **Ask Assistant**.
     - Verify answer: 18 annual leave days per calendar year.
     - Point out citations: `Sample Leave Policy v2.0 / Page 1 / Section 1. Annual Leave`.
  2. **Sick Leave Medical Certificate (Page 2 Multi-Page Citation)**: Select *"When is a medical certificate required for sick leave?"*
     - Verify answer: $\ge 3$ consecutive days requires a certificate from a registered medical practitioner.
     - Point out citation: `Sample Leave Policy v2.0 / Page 2 / Section 2. Sick Leave`.
  3. **Effective Date Handling (2025 vs 2026)**:
     - Set As-Of Date to `2025-10-01` -> Answers 15 days, citing `Sample Leave Policy v1.0`.
     - Set As-Of Date to `2026-03-01` -> Answers 18 days, citing `Sample Leave Policy v2.0`.
  4. **Prompt Injection Defense**: Select prompt injection probe (attempting to override system prompt and grant 100 days leave).
     - Verify that the model evaluates untrusted content securely inside XML boundaries without modifying policy rules.
  5. **Safe Abstention on Unsupported Query**: Select *"What is the reimbursement policy for interstellar spaceship travel?"*
     - Verify answer: The assistant explicitly abstains stating that policy documents do not contain evidence, citing zero fabricated sources.

---

### Step 7: Summary & Verification Metrics (30 Seconds)
- **Key Takeaways**:
  - Full Python 3.9 compatibility across all 11 core modules.
  - **159 passed automated tests in 74s** (100% pass rate across 16 test modules).
  - Production-grade Flask REST API with 24 endpoints and RBAC security.
  - 10 benchmark policy questions verified with multi-page citations and safe abstention.
  - Zero autonomous decision-making: complete manager/HR human authority.
  - All data is synthetic and privacy-preserving.
  - Ready for private Git repository submission and clean ZIP distribution (`package_submission.py`).
