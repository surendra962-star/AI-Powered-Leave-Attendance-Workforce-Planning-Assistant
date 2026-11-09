# Live Policy RAG Benchmark

- Run timestamp: `2026-11-08T08:41:24.711821+00:00`
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- Generation model: `llama3.2`
- Ollama available: `True`
- Passed cases: `11/11`
- Live generation check: `PASS`
- Indexed chunks: `21`
- Fixed benchmark cases: `11`

| ID | Category | Retrieval | Evidence | Answer Support | Result |
|---|---|---|---:|---|---|
| Q01 | Annual Leave Entitlement (Current) | PASS | 15 | PASS | PASS |
| Q02 | Sick Leave Notice & Certification | PASS | 12 | PASS | PASS |
| Q03 | Advance Notice Period | PASS | 13 | PASS | PASS |
| Q04 | Compensatory Off Validity | PASS | 7 | PASS | PASS |
| Q05 | Historical Version Routing (2025) | PASS | 5 | PASS | PASS |
| Q06 | Remote Work Allowance (PDF Page 2) | PASS | 7 | PASS | PASS |
| Q07 | Core Working Hours & Attendance (PDF Page 1) | PASS | 6 | PASS | PASS |
| Q08 | Working Days and Holidays Exclusion | PASS | 10 | PASS | PASS |
| Q09 | Conflicting Policies & Effective Dates | PASS | 8 | PASS | PASS |
| Q10 | Out-of-Scope Abstention | N/A | 0 | PASS | PASS |
| Q11 | Internal Leave Request Process | PASS | 14 | PASS | PASS |

## Retrieval Details

### Q01
- Sample Leave Policy v2.0 — 1. Annual Leave (Page 1, distance 0.2218)
- Sample Leave Policy v2.0 — 3. Working Days and Holidays (Page 1, distance 0.3635)
- Sample Leave Policy v2.0 — 4. Compensatory Off (Page 2, distance 0.4125)
- Sample Leave Policy v2.0 — 2. Sick Leave (Page 1, distance 0.467)
### Q02
- Sample Leave Policy v2.0 — 2. Sick Leave (Page 1, distance 0.2697)
- Synthetic Leave Request Process v1.0 — 2. Employee Submission Steps (Page 1, distance 0.5628)
- Sample Leave Policy v2.0 — 4. Compensatory Off (Page 2, distance 0.5652)
- Sample Leave Policy v2.0 — 1. Annual Leave (Page 1, distance 0.5814)
### Q03
- Sample Leave Policy v2.0 — 1. Annual Leave (Page 1, distance 0.4227)
- Sample Leave Policy v2.0 — 2. Sick Leave (Page 1, distance 0.4627)
- Sample Leave Policy v2.0 — 5. Approval and Escalation (Page 2, distance 0.4865)
- Sample Leave Policy v2.0 — 4. Compensatory Off (Page 2, distance 0.5368)
### Q04
- Sample Leave Policy v2.0 — 4. Compensatory Off (Page 2, distance 0.2958)
- Sample Leave Policy v2.0 — 3. Working Days and Holidays (Page 1, distance 0.5719)
- Sample Leave Policy v2.0 — 1. Annual Leave (Page 1, distance 0.5785)
- Synthetic Leave Request Process v1.0 — 5. Cancellation and Timeline Handling (Page 1, distance 0.6606)
### Q05
- Sample Leave Policy v1.0 — Annual Leave (Page 1, distance 0.3328)
- Sample Leave Policy v1.0 — Sick Leave (Page 1, distance 0.4394)
- Sample Leave Policy v1.0 — Planned Leave Notice (Page 1, distance 0.4447)
- Sample Leave Policy v1.0 — Sample Leave Policy — Version 1.0 (Page 1, distance 0.4671)
### Q06
- Attendance and Remote Work Policy v1.0 — Remote Work and Flexible Schedules (Page 2, distance 0.2999)
- Attendance and Remote Work Policy v1.0 — Core Working Hours and Attendance (Page 1, distance 0.4026)
- Sample Leave Policy v2.0 — 3. Working Days and Holidays (Page 1, distance 0.4565)
- Attendance and Remote Work Policy v1.0 — Policy Exceptions and Process Documentation (Page 3, distance 0.5287)
### Q07
- Attendance and Remote Work Policy v1.0 — Core Working Hours and Attendance (Page 1, distance 0.2684)
- Attendance and Remote Work Policy v1.0 — Policy Exceptions and Process Documentation (Page 3, distance 0.4171)
- Attendance and Remote Work Policy v1.0 — Remote Work and Flexible Schedules (Page 2, distance 0.4995)
- Sample Leave Policy v2.0 — 3. Working Days and Holidays (Page 1, distance 0.5673)
### Q08
- Sample Leave Policy v2.0 — 3. Working Days and Holidays (Page 1, distance 0.2801)
- Sample Leave Policy v2.0 — 1. Annual Leave (Page 1, distance 0.4646)
- Sample Leave Policy v2.0 — 4. Compensatory Off (Page 2, distance 0.5158)
- Synthetic Leave Request Process v1.0 — 2. Employee Submission Steps (Page 1, distance 0.6042)
### Q09
- Sample Leave Policy v2.0 — 4. Compensatory Off (Page 2, distance 0.4917)
- Sample Leave Policy v2.0 — 1. Annual Leave (Page 1, distance 0.5063)
- Sample Leave Policy v2.0 — 3. Working Days and Holidays (Page 1, distance 0.5665)
- Sample Leave Policy v2.0 — 2. Sick Leave (Page 1, distance 0.6033)
### Q10
- No evidence passed the configured distance threshold.
### Q11
- Sample Leave Policy v2.0 — 6. Team Coverage (Page 3, distance 0.3968)
- Synthetic Leave Request Process v1.0 — 4. Escalation Procedure (Page 1, distance 0.4287)
- Sample Leave Policy v2.0 — 5. Approval and Escalation (Page 2, distance 0.5457)
- Synthetic Leave Request Process v1.0 — 3. Manager Review Steps (Page 1, distance 0.5702)
