# Synthetic Leave Request and Escalation Procedure

<!-- page 1 -->
## 1. Purpose
This internal process document defines the synthetic workflow used by the AI HR Assistant demonstration.
It supplements the Sample Leave Policy and is for demo use only.

## 2. Employee Submission Steps
1. The employee signs in and opens the leave request page.
2. The employee selects annual, sick, or comp-off leave and enters the start and end dates.
3. The employee reviews the calculated working days, public holidays, optional holidays, overlapping leave, and available balance.
4. The employee submits the request. The request enters pending or needs-review status.

## 3. Manager Review Steps
1. The manager opens pending team leave requests.
2. The manager reviews the leave balance, overlapping requests, approval deadline, and team coverage recommendation.
3. The system calculates a recommendation from staffing rules, but the recommendation is not an automatic decision.
4. The manager approves or declines the request and may record a decision note.

## 4. Escalation Procedure
- Escalate to HR when team coverage falls below the configured minimum staffing percentage.
- Escalate to HR when leave records overlap an approved critical project deadline.
- Escalate to HR when an approval deadline is missed.
- Escalate to HR when policy evidence conflicts or the RAG assistant cannot find sufficient policy support.
- Do not automatically approve requests during escalation. Human review is required.

## 5. Cancellation and Timeline Handling
- An employee may cancel an eligible pending or approved leave request.
- Cancellation updates the leave status and releases the cancelled leave days where the application rules permit.
- Approval deadlines, project deadlines, return-to-work events, and reminders appear in the Timeline & Alerts section.
- Reminders in this demonstration are displayed as in-app alerts when the Streamlit application is open. They do not send email, SMS, or push notifications.
