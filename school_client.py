"""Client for the School Financial Management System's chatbot integration API.

The school system runs as its own service (see "School Financial Management
System/README.md"). Every call passes the parent's WhatsApp number, and the
school system only returns students whose guardian has that number.
"""
import hashlib
import hmac
import os

import requests
from dotenv import load_dotenv

load_dotenv()

SCHOOL_API_URL = os.getenv("SCHOOL_API_URL", "").rstrip("/")
SCHOOL_API_KEY = os.getenv("SCHOOL_API_KEY", "")
TIMEOUT = 15


class SchoolApiError(Exception):
    """The school system answered with an error (status is its HTTP code)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def is_configured():
    return bool(SCHOOL_API_URL and SCHOOL_API_KEY)


def _request(method, path, **kwargs):
    if not is_configured():
        raise SchoolApiError("School integration is not configured")
    try:
        resp = requests.request(
            method, f"{SCHOOL_API_URL}/api/integration{path}",
            headers={"Authorization": f"Bearer {SCHOOL_API_KEY}"},
            timeout=TIMEOUT, **kwargs,
        )
    except requests.RequestException as e:
        raise SchoolApiError(f"School system unreachable: {e}")
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        raise SchoolApiError(data.get("error") or f"HTTP {resp.status_code}", resp.status_code)
    return data


def find_guardian(phone):
    """Guardian name and children for a WhatsApp number, or None if not registered."""
    try:
        return _request("GET", "/guardian", params={"phone": phone})
    except SchoolApiError as e:
        if e.status == 404:
            return None
        raise


def get_account(student_id, phone):
    return _request("GET", f"/students/{int(student_id)}/account", params={"phone": phone})


def record_payment(student_id, phone, amount, reference):
    """Record a gateway-confirmed payment. Safe to retry: the school system
    returns the original receipt for a reference it has already recorded."""
    return _request("POST", "/payments", json={
        "student_id": student_id, "phone": phone, "amount": amount, "reference": reference,
    })


def get_announcements():
    return _request("GET", "/announcements")


def verify_notification(raw_body, signature_header):
    """Check the X-School-Signature header on a notification from the school system."""
    if not SCHOOL_API_KEY or not signature_header:
        return False
    expected = "sha256=" + hmac.new(SCHOOL_API_KEY.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
