from __future__ import annotations

from strands import tool

from connectors.base import Calendar


def build_calendar_tools(calendar: Calendar) -> list:

    @tool
    def list_pending_meeting_requests() -> list[dict]:
        """List all pending meeting requests awaiting a response."""
        return [
            {
                "id": r.id,
                "requester": r.requester,
                "requester_name": r.requester_name,
                "proposed_time": r.proposed_time,
                "duration_minutes": r.duration_minutes,
                "topic": r.topic,
            }
            for r in calendar.list_pending_requests()
        ]

    @tool
    def list_existing_events(start: str, end: str) -> list[dict]:
        """
        List the founder's existing calendar events in a time range, to check
        for conflicts before booking something new.

        Args:
            start: ISO timestamp for the start of the range to check.
            end: ISO timestamp for the end of the range to check.
        """
        return [
            {"id": e.id, "title": e.title, "start": e.start, "end": e.end}
            for e in calendar.list_events(start, end)
        ]

    @tool
    def book_meeting(request_id: str, start: str, end: str) -> str:
        """
        Book a pending meeting request onto the calendar. Only call this after
        checking list_existing_events for conflicts and confirming this slot
        respects the founder's scheduling preferences.

        Args:
            request_id: the id of the pending calendar request being booked.
            start: ISO timestamp for the confirmed start time.
            end: ISO timestamp for the confirmed end time.
        """
        event = calendar.book(request_id, start, end)
        return f"Booked '{event.title}' at {event.start} (event {event.id})."

    @tool
    def decline_meeting(request_id: str, reason: str) -> str:
        """
        Decline a pending meeting request autonomously (e.g. cold outreach,
        a clear scheduling conflict with no reasonable alternative slot).

        Args:
            request_id: the id of the pending calendar request being declined.
            reason: brief reason for declining, used in the polite decline message.
        """
        calendar.decline(request_id, reason)
        return f"Declined request {request_id}: {reason}"

    return [list_pending_meeting_requests, list_existing_events, book_meeting, decline_meeting]
