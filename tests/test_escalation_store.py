import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from memory.escalation_store import EscalationStore  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import memory.escalation_store as es

    monkeypatch.setattr(es, "DATA_DIR", tmp_path)
    return EscalationStore("test-founder")


def test_add_creates_open_escalation(store):
    esc = store.add("email", "em_001", "Involves a contract", "Forward to legal")
    assert esc.status == "open"
    assert esc.id == "esc_001"


def test_list_open_excludes_resolved(store):
    esc = store.add("email", "em_001", "reason", "action")
    store.resolve(esc.id, "Approved")
    assert store.list_open() == []


def test_reset_clears_all(store):
    store.add("email", "em_001", "reason", "action")
    store.reset()
    assert store.list_open() == []
