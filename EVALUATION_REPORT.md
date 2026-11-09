# AI HR Assistant - Evaluation Report

## Test Environment

- Evaluation date: 2026-11-09
- Operating system: macOS
- Runtime used for final verification: Python 3.13.9
- Test runner: pytest 8.4.2
- Database: isolated temporary SQLite databases for service tests; synthetic seed data
- Command: `python3 -m pytest -q`

The project setup accepts Python 3.9 or newer. The final run used the available
Python 3.13.9 interpreter with a virtual environment and locally installed dependencies.

## Full Test Suite Result

- Collected: 175
- Passed: 175
- Failed: 0
- Skipped: 0
- Duration: 28.56 seconds

## Evaluation Cases

| # | Requirement | Setup | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|---|
| 1 | Secure authentication and role scope | Seed synthetic users; authenticate employee, manager, and HR | Unauthorized employee/manager access is denied; HR scope is allowed | Employee, manager, and HR scopes behaved according to role boundaries | PASS | `tests/test_phase1_access_control.py`; full suite: 175 passed |
| 2 | Historical policy routing | Load leave policies at 2025-06-15 | The system returns leave policy v1.0 | v1.0 was selected for the historical date | PASS | `tests/test_rag_phase2.py`; `tests/test_rag_10_benchmark_questions.py` |
| 3 | Current policy citation | Ask an annual-leave question using the 2026 date | Current policy evidence and exact section/page citation are returned | v2.0 Annual Leave evidence was retrieved with citation | PASS | `tests/test_rag_10_benchmark_questions.py` |
| 4 | Unsupported-question abstention | Ask for a reimbursement policy not present in the documents | No unsupported answer is fabricated | No evidence passed the configured threshold | PASS | `tests/test_rag_phase2.py`; `tests/test_rag_10_benchmark_questions.py` |
| 5 | Policy conflict handling | Supply overlapping annual-leave policy versions in a unit test | Both versions and the conflict are disclosed | Conflict behavior and warning text were tested | PASS | `tests/test_rag_phase2.py` |
| 6 | Working-day calculation | Use a range containing weekends and a public holiday | Weekends and public holidays are excluded | Working-day calculation matched seeded rules | PASS | Phase 3 and leave-management tests |
| 7 | Leave balance update | Create/approve an eligible leave request | Balance used-days and available-days are updated correctly | Leave balance and decision workflows passed | PASS | `tests/test_phase3_complete.py` |
| 8 | Overlapping leave prevention | Submit leave that overlaps an existing request | The duplicate/overlap request is rejected or marked for review | Overlap validation passed | PASS | Phase 3 complete tests |
| 9 | Comp-off expiration | Seed an expired and an available comp-off record | Expired records are excluded from available balance | Comp-off status behavior passed | PASS | Timeline and Phase 4 tests |
| 10 | Low-coverage recommendation | Evaluate leave for a team below configured coverage | The system warns and records recommendation evidence | Coverage warning/evidence behavior passed | PASS | `tests/test_phase4_workforce_planning.py` |
| 11 | Deadline/backup conflict detection | Seed deadline, leave, team and backup records | The system surfaces deadline and backup information for human review | Workforce recommendation and backup tests passed | PASS | Phase 4 and Phase 7 tests |
| 12 | Internal process-document RAG | Register and split the synthetic leave-request process Markdown document | Process steps are indexed and citations can identify the document | Process document is registered, chunked, and available for retrieval | PASS | `data/policies/leave_request_process.md`; `tests/test_rag_phase2.py` |
| 13 | Analytics and dashboard output | Run employee, manager, HR, timeline, and analytics tests | Role-specific metrics and exports are produced | Dashboard/analytics suites passed | PASS | Phase 5 and integration tests |
| 14 | Flask API integration | Run Flask route and authentication tests | Login and protected routes return expected results or authorization errors | API integration suite passed | PASS | `tests/test_api_flask.py` |
| 15 | Audit and negative security behavior | Attempt invalid access and inspect audit actions | Unauthorized actions are denied and security events are auditable | Negative-security and audit tests passed | PASS | Negative security and audit test modules |
| 16 | Manager leave-review timeline | Ask for the manager review deadline through the RAG service and provide a synthetic generator | The answer states 3 business days and cites Section 5 | Deterministic policy extraction returned `3 business days` with the correct citation | PASS | `tests/test_rag_phase2.py`; `leave_policy_v2.md` |
