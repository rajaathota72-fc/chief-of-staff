"""
Local, JSON-backed fake inbox & calendar so the whole agent loop can be run and
demoed without any real Gmail/Calendar credentials.

Swap this for `google_connector.py` (same Inbox/Calendar interface) to go live -
nothing in agent.py or tools/ needs to change.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from dataclasses import fields

from .base import Calendar, CalendarEvent, CalendarRequest, Inbox, EmailMessage

_EMAIL_FIELDS = {f.name for f in fields(EmailMessage)}


def _to_email_message(raw: dict) -> EmailMessage:
    """Build an EmailMessage from stored JSON, ignoring extra bookkeeping keys
    (e.g. `sent_replies`, appended by send_reply) that aren't part of the dataclass."""
    return EmailMessage(**{k: v for k, v in raw.items() if k in _EMAIL_FIELDS})

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
INBOX_SEED = DATA_DIR / "inbox.seed.json"
INBOX_STATE = DATA_DIR / "inbox.json"
CALENDAR_SEED = DATA_DIR / "calendar.seed.json"
CALENDAR_STATE = DATA_DIR / "calendar.json"

# Strands can dispatch multiple tool calls from one turn concurrently (each on
# its own thread), so read-modify-write access to these shared JSON files must
# be serialized to avoid two concurrent write_text() calls interleaving and
# corrupting the file.
_INBOX_LOCK = threading.Lock()
_CALENDAR_LOCK = threading.Lock()


def reset_demo_data() -> None:
    """Copy the seed files over the working state files. Call before a fresh demo run."""
    INBOX_STATE.write_text(INBOX_SEED.read_text())
    CALENDAR_STATE.write_text(CALENDAR_SEED.read_text())


def _ensure_state() -> None:
    if not INBOX_STATE.exists() or not CALENDAR_STATE.exists():
        reset_demo_data()


class MockInbox(Inbox):
    def __init__(self) -> None:
        _ensure_state()

    def _load(self) -> list[dict]:
        return json.loads(INBOX_STATE.read_text())

    def _save(self, emails: list[dict]) -> None:
        INBOX_STATE.write_text(json.dumps(emails, indent=2))

    def list_unread(self) -> list[EmailMessage]:
        return [_to_email_message(e) for e in self._load() if e["status"] == "unread"]

    def get(self, email_id: str) -> EmailMessage:
        for e in self._load():
            if e["id"] == email_id:
                return _to_email_message(e)
        raise KeyError(f"No email with id {email_id}")

    def send_reply(self, email_id: str, body: str) -> None:
        with _INBOX_LOCK:
            emails = self._load()
            for e in emails:
                if e["id"] == email_id:
                    e["status"] = "handled"
                    e.setdefault("sent_replies", []).append(body)
            self._save(emails)

    def mark_status(self, email_id: str, status: str) -> None:
        with _INBOX_LOCK:
            emails = self._load()
            for e in emails:
                if e["id"] == email_id:
                    e["status"] = status
            self._save(emails)


class MockCalendar(Calendar):
    def __init__(self) -> None:
        _ensure_state()

    def _load(self) -> dict:
        return json.loads(CALENDAR_STATE.read_text())

    def _save(self, data: dict) -> None:
        CALENDAR_STATE.write_text(json.dumps(data, indent=2))

    def list_pending_requests(self) -> list[CalendarRequest]:
        data = self._load()
        return [CalendarRequest(**r) for r in data["requests"] if r["status"] == "pending"]

    def list_events(self, start: str, end: str) -> list[CalendarEvent]:
        data = self._load()
        # demo scope: return all events, real connector would filter by [start, end)
        return [CalendarEvent(**e) for e in data["events"]]

    def book(self, request_id: str, start: str, end: str) -> CalendarEvent:
        with _CALENDAR_LOCK:
            data = self._load()
            req = next((r for r in data["requests"] if r["id"] == request_id), None)
            if req is None:
                raise KeyError(f"No calendar request with id {request_id}")
            req["status"] = "booked"
            event = {
                "id": f"ev_{request_id}",
                "title": req["topic"],
                "start": start,
                "end": end,
                "attendees": [req["requester"]],
            }
            data["events"].append(event)
            self._save(data)
            return CalendarEvent(**event)

    def decline(self, request_id: str, reason: str) -> None:
        with _CALENDAR_LOCK:
            data = self._load()
            for r in data["requests"]:
                if r["id"] == request_id:
                    r["status"] = "declined"
                    r["decline_reason"] = reason
            self._save(data)
