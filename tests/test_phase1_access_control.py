import pytest

from access_control.service import authenticate, can_access_employee
from leave_management.service import (
    LeaveError,
    decide_leave_request,
    list_leave_requests,
)


def test_employee_manager_hr_scope_is_database_driven():
    employee = authenticate("E001", "rahuluser@2026")
    manager = authenticate("E005", "kiranmgr@2026")
    hr = authenticate("HR001", "hradmin@2026")

    assert can_access_employee(employee, "E001")
    assert not can_access_employee(employee, "E006")
    assert can_access_employee(manager, "E002")
    assert not can_access_employee(manager, "E006")
    assert can_access_employee(hr, "E006")


def test_role_lists_are_scoped_and_employee_cannot_see_other_leave():
    employee = authenticate("E001", "rahuluser@2026")
    own_records = list_leave_requests(employee, employee_id="E006")

    assert own_records
    assert all(row["employee_id"] == "E001" for row in own_records)


def test_manager_cannot_decide_leave_from_another_team():
    manager = authenticate("E005", "kiranmgr@2026")
    hr = authenticate("HR001", "hradmin@2026")
    cross_team_records = list_leave_requests(hr, employee_id="E006")
    assert cross_team_records
    request_id = cross_team_records[0]["request_id"]

    with pytest.raises(LeaveError, match="own team"):
        decide_leave_request(manager, request_id, "approved")


def test_employee_cannot_make_leave_decision():
    employee = authenticate("E001", "rahuluser@2026")

    with pytest.raises(LeaveError, match="Only a manager or HR"):
        decide_leave_request(employee, 999999, "declined")
