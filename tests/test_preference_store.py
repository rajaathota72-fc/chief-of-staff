import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from memory.preference_store import PreferenceStore  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import memory.preference_store as ps

    monkeypatch.setattr(ps, "DATA_DIR", tmp_path)
    return PreferenceStore("test-founder")


def test_starts_empty(store):
    assert store.list_all() == []
    assert "No learned preferences" in store.as_prompt_block()


def test_add_and_list(store):
    store.add("Always CC cofounder on hiring emails", "email")
    prefs = store.list_all()
    assert len(prefs) == 1
    assert prefs[0].rule == "Always CC cofounder on hiring emails"
    assert prefs[0].category == "email"
    assert prefs[0].source == "correction"


def test_prompt_block_formats_all_prefs(store):
    store.add("Rule one", "scheduling")
    store.add("Rule two", "email")
    block = store.as_prompt_block()
    assert "[scheduling] Rule one" in block
    assert "[email] Rule two" in block


def test_ids_increment(store):
    p1 = store.add("Rule one", "general")
    p2 = store.add("Rule two", "general")
    assert p1.id == "pref_001"
    assert p2.id == "pref_002"
