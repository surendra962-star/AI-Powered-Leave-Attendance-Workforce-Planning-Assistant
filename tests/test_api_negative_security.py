from unittest.mock import patch

import pytest

from api import app, _API_SESSIONS


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ALLOW_TEST_HEADERS"] = False
    with app.test_client() as test_client:
        yield test_client


def login(client, employee_id, password):
    response = client.post("/api/auth/login", json={
        "employee_id": employee_id,
        "password": password,
    })
    assert response.status_code == 200
    return response.get_json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_and_invalid_token_requests_are_rejected(client):
    assert client.get("/api/dashboard/employee").status_code == 401
    assert client.get(
        "/api/dashboard/employee",
        headers=bearer("invalid-token"),
    ).status_code == 401


def test_employee_peer_and_manager_other_team_scope_are_rejected(client):
    employee_token = login(client, "E001", "rahuluser@2026")
    peer = client.get(
        "/api/leave/balance?employee_id=E002&leave_type=annual&year=2026",
        headers=bearer(employee_token),
    )
    assert peer.status_code == 403

    manager_token = login(client, "E005", "kiranmgr@2026")
    cross_team = client.get(
        "/api/dashboard/manager?team_id=T02",
        headers=bearer(manager_token),
    )
    assert cross_team.status_code in (403, 401)


def test_hr_only_operations_reject_employee_and_manager(client):
    employee_token = login(client, "E001", "rahuluser@2026")
    response = client.get("/api/dashboard/hr", headers=bearer(employee_token))
    assert response.status_code == 403

    manager_token = login(client, "E005", "kiranmgr@2026")
    response = client.get("/api/admin/employees", headers=bearer(manager_token))
    assert response.status_code == 403


@pytest.mark.parametrize("payload", [{}, {"employee_id": "E001"}, None])
def test_malformed_or_missing_login_payloads_return_400(client, payload):
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 400
    assert response.is_json
    assert "error" in response.get_json()


def test_expired_token_is_rejected_and_removed(client):
    token = login(client, "E001", "rahuluser@2026")
    with patch.dict(_API_SESSIONS, _API_SESSIONS.copy(), clear=False):
        actor, _ = _API_SESSIONS[token]
        from datetime import datetime, timezone, timedelta
        _API_SESSIONS[token] = (actor, datetime.now(timezone.utc) - timedelta(seconds=1))
        response = client.get("/api/dashboard/employee", headers=bearer(token))
        assert response.status_code == 401
        assert token not in _API_SESSIONS


def test_bearer_token_not_vulnerable_to_client_role_headers(client):
    employee_token = login(client, "E001", "rahuluser@2026")
    forged = {
        "Authorization": f"Bearer {employee_token}",
        "X-Actor-ID": "HR001",
        "X-Actor-Role": "hr",
        "X-Actor-Team": "T01",
    }
    response = client.get("/api/admin/employees", headers=forged)
    assert response.status_code == 403
