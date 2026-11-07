# Live Demonstration & Evaluation Script
## AI-Powered Leave, Attendance & Workforce Planning Assistant

**Target Presentation Time**: 8–10 Minutes  
**Prerequisites**: Application running via `source .venv/bin/activate && python -m streamlit run app.py`

---

### Step 1: Architectural Overview & Role Boundaries (1 Minute)
- **Objective**: Explain the strict boundary between AI policy reasoning and deterministic business rules.
- **Narrative**:
  - *"Our system solves the HR automation challenge by separating grounded knowledge retrieval from mission-critical business logic."*
  - *"Deterministic rules compute working days, balance deductions, attendance percentages, and workforce coverage in pure Python and SQLite."*
  - *"RAG retrieves company policies from ChromaDB and uses local Ollama (`llama3.2`) to answer policy questions with verifiable section and page citations."*
  - *"Critically: the AI assistant never makes autonomous approval or rejection decisions. Managers and HR retain full decision authority."*

---

### Step 2: Employee Workspace Demonstration (2 Minutes)
- **Login Credentials**: `E001` / `rahuluser@2026` (Rahul Sharma, Senior AI Engineer)
- **Actions**:
  1. **Personal Dashboard**: Inspect leave balances (Annual: 18, Sick: 10), attendance summary, and available comp-off days.
  2. **Daily Clock-In**: In **Attendance Management**, click **🕒 Clock In Today**. Show that current time is logged immediately.
  3. **Leave Application**: Navigate to **Apply for Leave**:
     - Select `annual` leave for `2026-12-07` to `2026-12-09`.
     - Show the **Duration Preview** automatically calculating **3 working days** (excluding weekends).
     - Submit request. Show the confirmation: *"Submitted for human review. It has not been approved."*
  4. **Leave Cancellation**: Return to **My Dashboard**, expand *Cancel an Active or Pending Leave Request*, and cancel request `#1`. Show that balance remains intact.
  5. **Sign Out**: Click **🚪 Sign Out** in sidebar.

---

### Step 3: Manager Decision Support & Workforce Planning (2.5 Minutes)
- **Login Credentials**: `E005` / `kiranmgr@2026` (Kiran Rao, Engineering Manager)
- **Actions**:
  1. **Team Dashboard**: View team active headcount (6 active members in Team `T01`) and minimum required coverage (60%).
  2. **Manager Review**: Select pending leave request `#2` (or newly submitted request).
  3. **Evaluate Workforce Impact**: Click **🔍 Evaluate Workforce Impact & Coverage**:
     - Show deterministic daily coverage calculation.
     - Show whether team coverage drops below 60%.
     - Point out the explainable recommendation (`HIGH_RISK`, `REVIEW_REQUIRED`, or `LOW_RISK`) and detailed reasoning.
  4. **Human Decision**:
     - Emphasize the banner: *"AI Decision Support: Human retains final decision-making authority."*
     - Enter review note: *"Approved based on sprint deliverables."*
     - Click **Record Final Decision** as `approved`.
     - Show that the leave status updates and balances deduct atomically.
  5. **Critical Deadline & Backup Identification**:
     - Scroll to *Critical Deadlines & Backup Candidate Identification*.
     - Select project deadline `#1` (`Q4 Core AI Pipeline Delivery`).
     - Click **Identify Available Backup Candidates**. Show ranked team members with availability status.
  6. **Sign Out**.

---

### Step 4: HR Administration & Governance (2 Minutes)
- **Login Credentials**: `HR001` / `hradmin@2026` (HR Administrator)
- **Actions**:
  1. **Organization Overview**: View active headcount across all teams (`T01`, `T02`) and registered policy versions.
  2. **HR Employee Admin**:
     - Register a new employee (e.g. `E012`, `Ananya Sharma`, `T01`). Show immediate appearance in directory.
     - Demonstrate password updating for any synthetic employee.
  3. **Daily Attendance Overview**: View organization-wide daily clock-in/out records and click **📥 Download Full Attendance CSV**.
  4. **System Audit Logs**: Open **System Audit Logs** to show the immutable audit trail capturing logins, employee creations, comp-off grants, and leave approvals.
  5. **Workforce Analytics**:
     - Inspect monthly attendance percentage formula (`Present / (Present + Absent) * 100`).
     - Click **📥 Export Workforce Metrics CSV**.

---

### Step 5: HR Policy Assistant RAG Demonstration (1.5 Minutes)
- **Navigation**: Open **HR Policy Assistant (RAG)**
- **Test Questions**:
  1. **Annual Leave Entitlement**: Select *"How many annual leave days are provided per year?"*
     - Click **Ask Assistant**.
     - Verify answer: 18 annual leave days per calendar year.
     - Point out citations: `Sample Leave Policy v2.0 / Page 1 / Section 1. Annual Leave`.
  2. **Advance Notice Requirement**: Select *"How much advance notice is required for annual leave?"*
     - Verify answer: Minimum of 5 calendar days in advance.
  3. **Abstention on Unsupported Query**: Select *"What is the reimbursement policy for interstellar spaceship travel?"*
     - Verify answer: The assistant explicitly abstains stating that policy documents do not contain evidence, citing zero fabricated sources.
  4. **Effective Date Handling**: Change As-Of Date to `2025-10-01` and verify that the system references Policy Version 1.0 rather than Version 2.0.

---

### Step 6: Summary & Safety Disclaimers (30 Seconds)
- **Key Takeaways**:
  - Full Python 3.9 compatibility across all modules.
  - 53 passing automated tests.
  - Zero autonomous decision-making: complete manager/HR authority.
  - All data is synthetic and privacy-preserving.
