"""
Abstract interfaces for the data sources Chief of Staff reasons over.

Any concrete connector (mock, Gmail/Google Calendar, Outlook, etc.) implements
these two interfaces. The agent's tools only ever talk to `Inbox` / `Calendar`,
never to a specific vendor SDK, so swapping the backend is a one-file change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class EmailMessage:
    id: str
    thread_id: str
    sender: str
    sender_name: str
    subject: str
    body: str
    received_at: str  # ISO timestamp
    status: Literal["unread", "read", "handled", "snoozed", "escalated"] = "unread"


@dataclass
class CalendarRequest:
    id: str
    requester: str
    requester_name: str
    proposed_time: str  # ISO timestamp
    duration_minutes: int
    topic: str
    status: Literal["pending", "booked", "declined", "escalated"] = "pending"


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: str  # ISO timestamp
    end: str  # ISO timestamp
    attendees: list[str] = field(default_factory=list)


class Inbox(ABC):
    @abstractmethod
    def list_unread(self) -> list[EmailMessage]: ...

    @abstractmethod
    def get(self, email_id: str) -> EmailMessage: ...

    @abstractmethod
    def send_reply(self, email_id: str, body: str) -> None: ...

    @abstractmethod
    def mark_status(self, email_id: str, status: str) -> None: ...


class Calendar(ABC):
    @abstractmethod
    def list_pending_requests(self) -> list[CalendarRequest]: ...

    @abstractmethod
    def list_events(self, start: str, end: str) -> list[CalendarEvent]: ...

    @abstractmethod
    def book(self, request_id: str, start: str, end: str) -> CalendarEvent: ...

    @abstractmethod
    def decline(self, request_id: str, reason: str) -> None: ...
