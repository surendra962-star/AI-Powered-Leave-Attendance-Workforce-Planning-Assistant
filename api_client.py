"""HTTP client for Streamlit-to-Flask REST API integration.

Enables the Streamlit frontend to interact with the Python backend either over
HTTP REST requests or fallback to direct service calls if Flask is offline.
"""
from __future__ import annotations
import os
from datetime import date
from typing import Optional, Dict, Any, List, Union
import requests

from access_control.service import UserContext
from config import FLASK_API_URL

DEFAULT_API_BASE_URL = FLASK_API_URL


class FlaskAPIClient:
    """Client for invoking the Flask REST API backend over HTTP."""

    def __init__(self, base_url: str = DEFAULT_API_BASE_URL, timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.access_token: Optional[str] = None
        try:
            import streamlit as st
            self.access_token = st.session_state.get("api_access_token")
        except Exception:
            pass

    def _headers(self, actor: Optional[UserContext] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.access_token:
            headers["Authorization"] = "Bearer " + self.access_token
        return headers

    def _headers(self, actor: Optional[UserContext] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = "Bearer " + self.access_token
        return headers

    def is_healthy(self) -> bool:
        """Ping the Flask API /api/health endpoint."""
        try:
            resp = requests.get(f"{self.base_url}/api/health", timeout=2.0)
            return resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception:
            return False

    def login(self, employee_id: str, password: str) -> Dict[str, Any]:
        """Call POST /api/auth/login."""
        resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"employee_id": employee_id, "password": password},
            timeout=self.timeout
        )
        if resp.status_code != 200:
            err = resp.json().get("error", "Login failed") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            raise PermissionError(err)
        data = resp.json()
        self.access_token = data.get("access_token")
        return data

    def submit_leave_request(self, actor: UserContext, leave_type: str, start_date: str,
                             end_date: str, reason: str = "",
                             exclude_optional_holidays: bool = False) -> int:
        """Call POST /api/leave/request."""
        resp = requests.post(
            f"{self.base_url}/api/leave/request",
            json={
                "employee_id": actor.employee_id,
                "leave_type": leave_type,
                "start_date": start_date,
                "end_date": end_date,
                "reason": reason,
                "exclude_optional_holidays": exclude_optional_holidays,
                "submitted_on": date.today().isoformat()
            },
            headers=self._headers(actor),
            timeout=self.timeout
        )
        data = resp.json()
        if resp.status_code not in (200, 201):
            raise ValueError(data.get("error", "Leave submission failed"))
        return int(data["request_id"])

    def decide_leave_request(self, actor: UserContext, request_id: int, decision: str,
                             note: str = "", decided_on: Optional[str] = None) -> Dict[str, Any]:
        """Call POST /api/leave/decide."""
        resp = requests.post(
            f"{self.base_url}/api/leave/decide",
            json={
                "request_id": request_id,
                "decision": decision,
                "note": note,
                "decided_on": decided_on or date.today().isoformat()
            },
            headers=self._headers(actor),
            timeout=self.timeout
        )
        data = resp.json()
        if resp.status_code != 200:
            raise ValueError(data.get("error", "Decision recording failed"))
        return data

    def cancel_leave_request(self, actor: UserContext, request_id: int, reason: str = "") -> Dict[str, Any]:
        """Call POST /api/leave/cancel."""
        resp = requests.post(
            f"{self.base_url}/api/leave/cancel",
            json={"request_id": request_id, "reason": reason},
            headers=self._headers(actor),
            timeout=self.timeout
        )
        data = resp.json()
        if resp.status_code != 200:
            raise ValueError(data.get("error", "Cancellation failed"))
        return data

    def get_decision_history(self, request_id: int) -> List[Dict[str, Any]]:
        """Call GET /api/leave/decision-history/<id>."""
        resp = requests.get(
            f"{self.base_url}/api/leave/decision-history/{request_id}",
            timeout=self.timeout
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("decision_history", [])

    def clock_in(self, actor: UserContext, employee_id: Optional[str] = None) -> Dict[str, Any]:
        """Call POST /api/attendance/clock-in."""
        emp = employee_id or actor.employee_id
        resp = requests.post(
            f"{self.base_url}/api/attendance/clock-in",
            json={"employee_id": emp, "date": date.today().isoformat()},
            headers=self._headers(actor),
            timeout=self.timeout
        )
        data = resp.json()
        if resp.status_code != 200:
            raise ValueError(data.get("error", "Clock in failed"))
        return data

    def clock_out(self, actor: UserContext, employee_id: Optional[str] = None) -> Dict[str, Any]:
        """Call POST /api/attendance/clock-out."""
        emp = employee_id or actor.employee_id
        resp = requests.post(
            f"{self.base_url}/api/attendance/clock-out",
            json={"employee_id": emp, "date": date.today().isoformat()},
            headers=self._headers(actor),
            timeout=self.timeout
        )
        data = resp.json()
        if resp.status_code != 200:
            raise ValueError(data.get("error", "Clock out failed"))
        return data

    def get_employee_dashboard(self, actor: UserContext) -> Dict[str, Any]:
        """Call GET /api/dashboard/employee."""
        resp = requests.get(
            f"{self.base_url}/api/dashboard/employee",
            headers=self._headers(actor),
            timeout=self.timeout
        )
        if resp.status_code != 200:
            raise RuntimeError(resp.json().get("error", "Failed to fetch employee dashboard"))
        return resp.json()

    def get_manager_dashboard(self, actor: UserContext, team_id: Optional[str] = None) -> Dict[str, Any]:
        """Call GET /api/dashboard/manager."""
        params = {}
        if team_id:
            params["team_id"] = team_id
        resp = requests.get(
            f"{self.base_url}/api/dashboard/manager",
            params=params,
            headers=self._headers(actor),
            timeout=self.timeout
        )
        if resp.status_code != 200:
            raise PermissionError(resp.json().get("error", "Failed to fetch manager dashboard"))
        return resp.json()

    def get_hr_dashboard(self, actor: UserContext) -> Dict[str, Any]:
        """Call GET /api/dashboard/hr."""
        resp = requests.get(
            f"{self.base_url}/api/dashboard/hr",
            headers=self._headers(actor),
            timeout=self.timeout
        )
        if resp.status_code != 200:
            raise PermissionError(resp.json().get("error", "Failed to fetch HR dashboard"))
        return resp.json()

    def evaluate_leave_request(self, actor: UserContext, request_id: int) -> Dict[str, Any]:
        """Call POST /api/workforce/evaluate."""
        resp = requests.post(
            f"{self.base_url}/api/workforce/evaluate",
            json={"request_id": request_id},
            headers=self._headers(actor),
            timeout=self.timeout
        )
        data = resp.json()
        if resp.status_code != 200:
            raise ValueError(data.get("error", "Evaluation failed"))
        return data

    def get_workforce_metrics(self, actor: UserContext, month: str, team_id: Optional[str] = None,
                             employee_id: Optional[str] = None, leave_type: Optional[str] = None,
                             status: Optional[str] = None) -> Dict[str, Any]:
        """Call GET /api/analytics/metrics."""
        params = {"month": month}
        if team_id:
            params["team_id"] = team_id
        if employee_id:
            params["employee_id"] = employee_id
        if leave_type:
            params["leave_type"] = leave_type
        if status:
            params["status"] = status
        resp = requests.get(
            f"{self.base_url}/api/analytics/metrics",
            params=params,
            headers=self._headers(actor),
            timeout=self.timeout
        )
        if resp.status_code != 200:
            raise ValueError(resp.json().get("error", "Failed to fetch analytics metrics"))
        return resp.json()

    def get_team_coverage_analytics(self, actor: UserContext, team_id: str,
                                   start_date: str, end_date: str) -> Dict[str, Any]:
        """Call GET /api/analytics/team-coverage."""
        resp = requests.get(
            f"{self.base_url}/api/analytics/team-coverage",
            params={"team_id": team_id, "start_date": start_date, "end_date": end_date},
            headers=self._headers(actor),
            timeout=self.timeout
        )
        if resp.status_code != 200:
            raise ValueError(resp.json().get("error", "Failed to fetch team coverage analytics"))
        return resp.json()

    def ask_rag(self, question: str, on_date: Optional[str] = None,
                llm_model: str = "llama3.2") -> Dict[str, Any]:
        """Call POST /api/rag/ask."""
        resp = requests.post(
            f"{self.base_url}/api/rag/ask",
            json={
                "question": question,
                "as_of": on_date or date.today().isoformat(),
                "llm_model": llm_model
            },
            timeout=30.0
        )
        if resp.status_code != 200:
            raise ValueError(resp.json().get("error", "RAG query failed"))
        return resp.json()

    def get_alerts(self, actor: UserContext, horizon_days: int = 30) -> List[Dict[str, Any]]:
        """Call GET /api/timeline/alerts."""
        resp = requests.get(
            f"{self.base_url}/api/timeline/alerts",
            params={"horizon_days": horizon_days},
            headers=self._headers(actor),
            timeout=self.timeout
        )
        if resp.status_code != 200:
            return []
        return resp.json()
