import json

import pytest
from fastapi.testclient import TestClient

from app.core.schemas import DiscussionMessage
from app.main import app
from app.services.chunker import create_chunks
from app.services.extractor import DecisionExtractor


class MockProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(decisions):
    return json.dumps({"decisions": decisions})


def msg(number, content, author="A"):
    return DiscussionMessage(message_id="message_{}".format(number),
                             author=author, content=content)


def test_model_response_is_parsed_and_evidence_verified():
    provider = MockProvider([response([{
        "proposal": "Use PostgreSQL", "status": "accepted",
        "reason": None, "outcome_basis": "explicit_acceptance",
        "evidence": [{"segment_id": "message_1",
                      "quote": "I agree: use PostgreSQL"}],
    }])])
    decisions = DecisionExtractor(provider).extract(
        [msg(1, "I agree: use PostgreSQL")])
    assert len(decisions) == 1
    assert decisions[0].verified is True
    assert decisions[0].decision_id.startswith("proposal_")


@pytest.mark.parametrize("raw, error", [
    ("not json", "malformed JSON"),
    ("", "empty extraction response"),
    ("{}", "decisions array"),
])
def test_invalid_model_responses_are_visible(raw, error):
    with pytest.raises(RuntimeError, match=error):
        DecisionExtractor(MockProvider([raw])).extract([msg(1, "Proposal text")])


def test_later_chunk_updates_existing_proposal_and_accumulates_evidence():
    first = [{
        "proposal": "MongoDB", "status": "unresolved", "reason": None,
        "outcome_basis": "unresolved",
        "evidence": [{"segment_id": "message_1", "quote": "I propose MongoDB"}],
    }]
    second = [{
        "proposal": "MongoDB", "status": "rejected",
        "reason": "relational consistency", "outcome_basis": "explicit_rejection",
        "evidence": [{"segment_id": "message_2", "quote": "reject MongoDB for relational consistency"}],
    }]
    provider = MockProvider([response(first), response(second)])
    decisions = DecisionExtractor(provider, chunk_size=1).extract([
        msg(1, "I propose MongoDB"),
        msg(2, "We should reject MongoDB for relational consistency"),
    ])
    assert len(decisions) == 1
    assert decisions[0].status == "rejected"
    assert len(decisions[0].evidence) == 2
    assert "MongoDB" in provider.prompts[1]


def test_duplicate_proposal_is_updated_not_duplicated():
    provider = MockProvider([response([
        {"proposal": "Use PostgreSQL", "status": "unresolved",
         "outcome_basis": "unresolved", "evidence": []},
        {"proposal": "Use PostgreSQL", "status": "accepted",
         "outcome_basis": "explicit_acceptance", "evidence": []},
    ])])
    decisions = DecisionExtractor(provider).extract([msg(1, "PostgreSQL")])
    assert len(decisions) == 1
    assert decisions[0].status == "accepted"


def test_invalid_evidence_is_removed_and_unresolved_kept():
    provider = MockProvider([response([{
        "proposal": "Kafka", "status": "unresolved", "reason": None,
        "outcome_basis": "unresolved",
        "evidence": [{"segment_id": "message_99", "quote": "invented quote"}],
    }])])
    decisions = DecisionExtractor(provider).extract([msg(1, "Maybe Kafka")])
    assert decisions[0].status == "unresolved"
    assert decisions[0].evidence == []
    assert decisions[0].verified is False


def test_chunker_preserves_chronological_order():
    messages = [msg(i, "text {}".format(i)) for i in range(5)]
    assert [[m.message_id for m in c] for c in create_chunks(messages, 2)] == [
        ["message_0", "message_1"], ["message_2", "message_3"], ["message_4"]]


def test_api_surfaces_model_failure():
    from app.api import extract as extract_module

    class BrokenExtractor:
        def extract(self, messages):
            raise RuntimeError("model unavailable")

    original = extract_module.DecisionExtractor
    extract_module.DecisionExtractor = BrokenExtractor
    try:
        client = TestClient(app)
        result = client.post("/api/extract", json={
            "text": "Alice: This is a sufficiently long discussion."
        })
        assert result.status_code == 500
        assert "model unavailable" in result.json()["detail"]
    finally:
        extract_module.DecisionExtractor = original
