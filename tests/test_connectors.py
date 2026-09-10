import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """Point the mock connector's data dir at a temp dir seeded with tiny fixtures."""
    import connectors.mock_connector as mc

    inbox_seed = [
        {
            "id": "em_001",
            "thread_id": "th_001",
            "sender": "a@x.com",
            "sender_name": "A",
            "subject": "Hi",
            "body": "Body",
            "received_at": "2026-01-01T00:00:00",
            "status": "unread",
        }
    ]
    calendar_seed = {
        "requests": [
            {
                "id": "cr_001",
                "requester": "b@x.com",
                "requester_name": "B",
                "proposed_time": "2026-01-01T10:00:00",
                "duration_minutes": 30,
                "topic": "Chat",
                "status": "pending",
            }
        ],
        "events": [],
    }

    seed_inbox = tmp_path / "inbox.seed.json"
    seed_cal = tmp_path / "calendar.seed.json"
    seed_inbox.write_text(json.dumps(inbox_seed))
    seed_cal.write_text(json.dumps(calendar_seed))

    monkeypatch.setattr(mc, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mc, "INBOX_SEED", seed_inbox)
    monkeypatch.setattr(mc, "INBOX_STATE", tmp_path / "inbox.json")
    monkeypatch.setattr(mc, "CALENDAR_SEED", seed_cal)
    monkeypatch.setattr(mc, "CALENDAR_STATE", tmp_path / "calendar.json")

    mc.reset_demo_data()
    return mc


def test_list_unread(wired):
    inbox = wired.MockInbox()
    unread = inbox.list_unread()
    assert len(unread) == 1
    assert unread[0].id == "em_001"


def test_send_reply_marks_handled(wired):
    inbox = wired.MockInbox()
    inbox.send_reply("em_001", "Thanks!")
    assert inbox.list_unread() == []
    assert inbox.get("em_001").status == "handled"


def test_snooze(wired):
    inbox = wired.MockInbox()
    inbox.mark_status("em_001", "snoozed")
    assert inbox.get("em_001").status == "snoozed"


def test_book_meeting(wired):
    calendar = wired.MockCalendar()
    assert len(calendar.list_pending_requests()) == 1
    event = calendar.book("cr_001", "2026-01-01T10:00:00", "2026-01-01T10:30:00")
    assert event.title == "Chat"
    assert calendar.list_pending_requests() == []


def test_decline_meeting(wired):
    calendar = wired.MockCalendar()
    calendar.decline("cr_001", "Not a fit")
    assert calendar.list_pending_requests() == []
