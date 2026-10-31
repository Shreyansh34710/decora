import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.schemas import Alternative, Evidence, RejectionReason
from app.main import app
from app.services.memory import DecisionMemory, _CREATE_TABLE


def sample_decision(status="rejected", quote="We reject SQLite for poor replication"):
    evidence = Evidence(
        segment_id="message_1", quote=quote, author="Alice", timestamp="2026-01-01T10:00:00Z",
        source_url="https://example.test/discussion/1", quote_verified=True, supports_claim=True,
    )
    return Alternative(
        decision_id="proposal_0001", proposal="Use SQLite", status=status,
        reason="poor replication", outcome_basis="explicit_rejection",
        evidence=[evidence], outcome_evidence=[evidence],
        rejection_reasons=[RejectionReason(text="poor replication", evidence=[evidence])],
        verified=True,
    )


def test_database_initialization_creates_decisions_table(tmp_path):
    path = tmp_path / "memory.db"
    store = DecisionMemory(str(path))

    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert "decisions" in tables
    assert store.list_decisions() == []


def test_phase3_schema_migrates_without_losing_saved_decisions(tmp_path):
    path = tmp_path / "phase3.db"
    legacy_sql = _CREATE_TABLE.replace(", 'contested'", "").replace(
        "    source_repository TEXT,\n", "")
    values = (
        "legacy-id", "legacy-source", "use sqlite", "Use SQLite", "rejected",
        "explicit_rejection", "poor replication", "Legacy thread", "source:legacy",
        "[]", "[]", "[]", "", "[]", "[]", 0, "{}", "2026-01-01", "2026-01-01",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(legacy_sql)
        connection.execute("CREATE INDEX idx_decisions_created_at ON decisions(created_at DESC)")
        connection.execute(
            "INSERT INTO decisions VALUES (" + ",".join("?" for _ in values) + ")", values)
    store = DecisionMemory(str(path))

    preserved = store.list_decisions()[0]
    assert preserved["id"] == "legacy-id"
    assert preserved["status"] == "rejected"
    assert preserved["source_title"] == "Legacy thread"
    assert preserved["source_repository"] is None

    contested = sample_decision(status="contested")
    store.save("New", "new source", [contested], "source:new")
    assert any(item["status"] == "contested" for item in store.list_decisions())


def test_save_and_retrieve_preserve_source_and_reason_evidence_associations(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    result = store.save(
        "Database discussion", "Alice: We reject SQLite for poor replication.",
        [sample_decision()], "https://example.test/discussion/1",
        "https://github.com/acme/decora",
    )

    saved = store.list_decisions()[0]

    assert result["persisted"] is True
    assert saved["id"] == result["decision_ids"][0]
    assert saved["source_title"] == "Database discussion"
    assert saved["source_reference"] == "https://example.test/discussion/1"
    assert saved["source_repository"] == "https://github.com/acme/decora"
    assert saved["source_timestamps"] == ["2026-01-01T10:00:00Z"]
    assert saved["outcome_evidence"][0]["quote"] == "We reject SQLite for poor replication"
    assert saved["rejection_reasons"][0]["text"] == "poor replication"
    assert saved["rejection_reasons"][0]["evidence"][0]["segment_id"] == "message_1"
    assert saved["rejection_reasons"][0]["evidence"][0]["source_url"] == "https://example.test/discussion/1"


def test_keyword_search_covers_proposal_summary_and_rejection_reasons(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    store.save("Database", "discussion", [sample_decision()])

    assert len(store.list_decisions(query="SQLite")) == 1
    assert len(store.list_decisions(query="poor replication")) == 1
    assert len(store.list_decisions(query="poor")) == 1
    assert store.list_decisions(query="absent") == []


def test_repeated_save_returns_same_stable_id_without_duplicate_rows(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    arguments = ("Database", "same source text", [sample_decision()])

    first = store.save(*arguments)
    second = store.save(*arguments)

    assert first["decision_ids"] == second["decision_ids"]
    assert len(store.list_decisions()) == 1


def test_conflicting_reanalysis_keeps_original_record_and_reports_conflict(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    source = "Alice: We reject SQLite for poor replication."
    first = store.save("Database", source, [sample_decision()])
    conflicting = store.save("Database", source, [sample_decision(
        status="accepted", quote="The team accepts SQLite")])

    saved = store.list_decisions()[0]
    assert conflicting["persisted"] is False
    assert conflicting["conflicts"] == ["Use SQLite"]
    assert conflicting["decision_ids"] == []
    assert saved["id"] == first["decision_ids"][0]
    assert saved["status"] == "rejected"
    assert saved["outcome_evidence"][0]["quote"] == "We reject SQLite for poor replication"


def test_changed_source_evidence_with_same_reference_is_a_conflict(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    reference = "https://example.test/database-thread"
    store.save("Database", "original text", [sample_decision()], reference)

    result = store.save(
        "Database", "revised text", [sample_decision(quote="The team accepts SQLite")], reference)

    assert result["persisted"] is False
    assert result["conflicts"] == ["Use SQLite"]
    assert len(store.list_decisions()) == 1
    assert store.list_decisions()[0]["status"] == "rejected"


def test_related_retrieval_matches_keywords_and_excludes_unrelated_records(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    store.save("History", "one", [sample_decision()], "source:sqlite")
    unrelated = sample_decision()
    unrelated.proposal = "Use Redis cache"
    store.save("History", "two", [unrelated], "source:redis")

    result = store.find_related(
        [{"proposal": "Adopt SQLite", "status": "accepted"}],
        "Current", "new discussion", "source:current")

    assert [item["proposal"] for item in result] == ["Use SQLite"]
    assert result[0]["matched_proposals"] == ["Adopt SQLite"]
    assert result[0]["relevance_score"] == 1.0


def test_related_retrieval_excludes_current_source(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    source = "Alice: We reject SQLite for poor replication."
    reference = "source:current"
    store.save("Database", source, [sample_decision()], reference)

    result = store.find_related(
        [{"proposal": "Use SQLite", "status": "rejected"}],
        "Database", source, reference)

    assert result == []


def test_blank_source_reference_falls_back_to_title_and_text_for_exclusion(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    source = "Alice: We reject SQLite for poor replication."
    store.save("Database", source, [sample_decision()], "   ")

    result = store.find_related(
        [{"proposal": "Use SQLite", "status": "rejected"}],
        "Database", source, "   ")

    assert result == []


def test_retrieval_returns_all_outcomes_and_marks_only_potential_conflicts(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    for index, status in enumerate(("accepted", "rejected", "unresolved", "contested")):
        decision = sample_decision(status=status)
        store.save("Historical {}".format(index), "source {}".format(index),
                   [decision], "source:{}".format(index))

    result = store.find_related(
        [{"proposal": "Use SQLite", "status": "accepted"}],
        "Current", "new discussion", "source:new")

    assert {item["status"] for item in result} == {
        "accepted", "rejected", "unresolved", "contested",
    }
    conflicts = {item["status"]: item["potential_conflict"] for item in result}
    assert conflicts == {
        "accepted": False, "rejected": True,
        "unresolved": False, "contested": True,
    }


def test_opposite_proposal_directions_are_labeled_potential_conflicts(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    historical = sample_decision(status="accepted")
    historical.proposal = "Use Redis cache"
    store.save("History", "old", [historical], "source:old")

    result = store.find_related(
        [{"proposal": "Do not use Redis cache", "status": "accepted"}],
        "Current", "new", "source:new")

    assert len(result) == 1
    assert result[0]["potential_conflict"] is True
    assert result[0]["conflict_reasons"] == ["the proposal directions differ"]


def test_opposite_direction_is_flagged_even_when_new_outcome_is_unresolved(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    historical = sample_decision(status="accepted")
    historical.proposal = "Use Redis cache"
    store.save("History", "old", [historical], "source:old")

    result = store.find_related(
        [{"proposal": "Do not use Redis cache", "status": "unresolved"}],
        "Current", "new", "source:new")

    assert result[0]["potential_conflict"] is True
    assert result[0]["conflict_reasons"] == ["the proposal directions differ"]


def test_historical_match_preserves_source_and_evidence_traceability(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))
    store.save(
        "Old SQLite thread", "original text", [sample_decision()],
        "https://example.test/old-sqlite",
    )

    result = store.find_related(
        [{"proposal": "Adopt SQLite", "status": "accepted"}],
        "New thread", "new source", "https://example.test/new")

    assert result[0]["source_title"] == "Old SQLite thread"
    assert result[0]["source_reference"] == "https://example.test/old-sqlite"
    assert result[0]["evidence"][0]["quote"] == "We reject SQLite for poor replication"
    assert result[0]["evidence"][0]["author"] == "Alice"
    assert result[0]["evidence"][0]["quote_verified"] is True
    assert result[0]["rejection_reasons"][0]["evidence"][0]["quote"] == result[0]["evidence"][0]["quote"]


def test_empty_database_and_no_keyword_match_return_empty_lists(tmp_path):
    store = DecisionMemory(str(tmp_path / "memory.db"))

    assert store.find_related([{"proposal": "Use PostgreSQL"}], "Current", "text") == []
    store.save("History", "old", [sample_decision()], "source:old")
    assert store.find_related([{"proposal": "Use Cassandra"}], "Current", "new") == []


class FixedExtractor:
    provider = SimpleNamespace(model="qwen3:8b")

    def extract(self, messages):
        return [sample_decision()]


def test_repeated_analysis_persists_once_and_search_api_returns_source(monkeypatch, tmp_path):
    monkeypatch.setenv("DECORA_DB_PATH", str(tmp_path / "api.db"))
    from app.api import extract as extract_module
    monkeypatch.setattr(extract_module, "DecisionExtractor", FixedExtractor)
    client = TestClient(app)
    request = {
        "title": "Database thread",
        "source_reference": "https://example.test/thread/42",
        "text": "Alice: We reject SQLite for poor replication.",
    }

    first = client.post("/api/extract", json=request)
    second = client.post("/api/extract", json=request)
    listed = client.get("/api/memory")
    found = client.get("/api/memory/search", params={"q": "replication"})

    assert first.status_code == second.status_code == 200
    assert first.json()["memory_decision_ids"] == second.json()["memory_decision_ids"]
    assert first.json()["memory_persisted"] is True
    assert len(listed.json()) == 1
    assert len(found.json()) == 1
    assert found.json()[0]["source_reference"] == request["source_reference"]
    assert found.json()[0]["rejection_reasons"][0]["evidence"][0]["quote"].startswith("We reject")


def test_extraction_returns_historical_matches_with_potential_conflict(monkeypatch, tmp_path):
    monkeypatch.setenv("DECORA_DB_PATH", str(tmp_path / "api.db"))
    store = DecisionMemory()
    store.save(
        "Earlier SQLite decision", "older source", [sample_decision(
            status="accepted", quote="The team accepts SQLite")], "source:old")
    from app.api import extract as extract_module
    monkeypatch.setattr(extract_module, "DecisionExtractor", FixedExtractor)

    response = TestClient(app).post("/api/extract", json={
        "title": "Current discussion",
        "source_reference": "source:current",
        "text": "Alice: We reject SQLite for poor replication.",
    })

    assert response.status_code == 200
    historical = response.json()["historical_decisions"]
    assert len(historical) == 1
    assert historical[0]["status"] == "accepted"
    assert historical[0]["potential_conflict"] is True
    assert historical[0]["source_title"] == "Earlier SQLite decision"
    assert historical[0]["source_reference"] == "source:old"
    assert historical[0]["evidence"][0]["quote"] == "The team accepts SQLite"


def test_related_memory_api_validates_input_and_returns_no_match(monkeypatch, tmp_path):
    monkeypatch.setenv("DECORA_DB_PATH", str(tmp_path / "api.db"))
    client = TestClient(app)
    payload = {
        "proposals": [{"proposal": "Use PostgreSQL", "status": "accepted"}],
        "source_title": "Current",
        "source_text": "A current discussion source.",
    }

    assert client.post("/api/memory/related", json=payload).json() == []
    assert client.post("/api/memory/related", json={**payload, "proposals": []}).status_code == 422
    assert client.post("/api/memory/related", json={
        **payload, "proposals": [{"proposal": " "}],
    }).status_code == 422


def test_related_memory_api_reports_database_failure(monkeypatch):
    from app.api import memory as memory_module

    def unavailable():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(memory_module, "get_memory_store", unavailable)
    response = TestClient(app).post("/api/memory/related", json={
        "proposals": [{"proposal": "Use SQLite"}],
        "source_title": "Current",
        "source_text": "Some source discussion.",
    })

    assert response.status_code == 503


def test_memory_api_validates_search_and_pagination(monkeypatch, tmp_path):
    monkeypatch.setenv("DECORA_DB_PATH", str(tmp_path / "api.db"))
    client = TestClient(app)

    assert client.get("/api/memory/search").status_code == 422
    assert client.get("/api/memory/search", params={"q": "x" * 201}).status_code == 422
    assert client.get("/api/memory", params={"limit": 0}).status_code == 422
    assert client.get("/api/memory", params={"offset": -1}).status_code == 422
    assert client.post("/api/extract", json={
        "source_reference": "x" * 2001,
        "text": "This discussion has enough characters for the API request.",
    }).status_code == 422


def test_memory_api_reports_database_unavailable(monkeypatch):
    from app.api import memory as memory_module

    def unavailable():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(memory_module, "get_memory_store", unavailable)
    response = TestClient(app).get("/api/memory")

    assert response.status_code == 503
    assert response.json()["detail"] == "Decision memory is unavailable."


def test_extraction_reports_memory_storage_unavailable(monkeypatch):
    from app.api import extract as extract_module

    class StorageFailure:
        def save(self, **kwargs):
            raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(extract_module, "DecisionExtractor", FixedExtractor)
    monkeypatch.setattr(extract_module, "get_memory_store", StorageFailure)
    response = TestClient(app).post("/api/extract", json={
        "title": "Database",
        "text": "This discussion has enough characters for extraction and storage.",
    })

    assert response.status_code == 503
    assert "could not be saved" in response.json()["detail"]
