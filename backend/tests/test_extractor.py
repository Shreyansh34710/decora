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
        "outcome_evidence": [{"segment_id": "message_1",
                               "quote": "The team accepts PostgreSQL", "supports_claim": True}],
    }])])
    decisions = DecisionExtractor(provider).extract(
        [msg(1, "The team accepts PostgreSQL")])
    assert len(decisions) == 1
    assert decisions[0].verified is True
    assert decisions[0].decision_id.startswith("proposal_")
    assert decisions[0].status == "accepted"
    assert len(decisions[0].history) == 1


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
        "outcome_evidence": [{"segment_id": "message_2", "quote": "We reject MongoDB for relational consistency"}],
    }]
    provider = MockProvider([response(first), response(second)])
    decisions = DecisionExtractor(provider, chunk_size=1).extract([
        msg(1, "I propose MongoDB"),
        msg(2, "We reject MongoDB for relational consistency"),
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
         "outcome_basis": "explicit_acceptance",
         "outcome_evidence": [{"segment_id": "message_1", "quote": "We accept PostgreSQL", "supports_claim": True}]},
    ])])
    decisions = DecisionExtractor(provider).extract([msg(1, "We accept PostgreSQL")])
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


def test_same_proposal_reworded_across_chunks_keeps_stable_identity_and_history():
    provider = MockProvider([
        response([{"proposal": "Use PostgreSQL for storage", "status": "unresolved",
                   "outcome_basis": "unresolved", "evidence": [
                       {"segment_id": "message_1", "quote": "I propose PostgreSQL", "supports_claim": None}]}]),
        response([{"proposal_id": "proposal_0001", "proposal": "Adopt PostgreSQL as the database",
                   "status": "accepted", "outcome_basis": "consensus", "outcome_evidence": [
                       {"segment_id": "message_2", "quote": "The team agreed PostgreSQL is our database", "supports_claim": True}]}]),
    ])
    result = DecisionExtractor(provider, chunk_size=1).extract([
        msg(1, "I propose PostgreSQL"), msg(2, "The team agreed PostgreSQL is our database")])
    assert len(result) == 1
    assert result[0].decision_id == "proposal_0001"
    assert result[0].status == "accepted"
    assert [e.segment_id for e in result[0].outcome_evidence] == ["message_2"]
    assert len(result[0].history) == 1


def test_similar_but_distinct_proposals_remain_separate():
    provider = MockProvider([response([
        {"proposal": "Use PostgreSQL for analytics", "status": "unresolved", "outcome_basis": "unknown"},
        {"proposal": "Use PostgreSQL for user authentication", "status": "unresolved", "outcome_basis": "unknown"},
    ])])
    result = DecisionExtractor(provider).extract([msg(1, "Compare PostgreSQL analytics and authentication stores")])
    assert len(result) == 2
    assert result[0].decision_id != result[1].decision_id


def test_individual_objection_does_not_override_later_project_acceptance():
    provider = MockProvider([
        response([{"proposal": "Use Redis cache", "status": "unresolved", "outcome_basis": "unresolved"}]),
        response([{"proposal_id": "proposal_0001", "proposal": "Adopt Redis cache", "status": "rejected",
                   "outcome_basis": "individual_opinion", "outcome_evidence": [
                       {"segment_id": "message_2", "quote": "I object to Redis", "supports_claim": True}]}]),
        response([{"proposal_id": "proposal_0001", "proposal": "Use Redis cache", "status": "accepted",
                   "outcome_basis": "explicit_acceptance", "outcome_evidence": [
                       {"segment_id": "message_3", "quote": "The team approves Redis", "supports_claim": True}]}]),
    ])
    result = DecisionExtractor(provider, chunk_size=1).extract([
        msg(1, "I propose Redis"), msg(2, "I object to Redis"), msg(3, "The team approves Redis")])
    assert result[0].status == "accepted"
    assert result[0].outcome_basis == "explicit_acceptance"


def test_question_quote_is_preserved_but_not_counted_as_logical_outcome_support():
    question = "Why does this not allow assignment to attributes and subscripts?"
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Allow assignment to attributes and subscripts",
        "status": "rejected", "outcome_basis": "explicit_rejection",
        "outcome_evidence": [{"segment_id": "message_1", "quote": question, "supports_claim": True}],
    }])])).extract([msg(1, question, author="Random832")])
    assert result[0].status == "unresolved"
    assert result[0].outcome_basis == "unresolved"
    assert result[0].outcome_evidence == []
    assert result[0].evidence[0].quote == question
    assert result[0].evidence[0].supports_claim is None


def test_individual_objection_is_not_a_project_rejection():
    objection = "I oppose using Redis for this service."
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Use Redis", "status": "rejected", "outcome_basis": "individual_opinion",
        "outcome_evidence": [{"segment_id": "message_1", "quote": objection, "supports_claim": True}],
    }])])).extract([msg(1, objection, author="One maintainer")])
    assert result[0].status == "unresolved"
    assert result[0].outcome_basis == "individual_opinion"
    assert result[0].history == []


def test_individual_objection_does_not_overwrite_existing_project_acceptance():
    provider = MockProvider([
        response([{"proposal": "Use Redis", "status": "accepted",
                   "outcome_basis": "explicit_acceptance", "outcome_evidence": [
                       {"segment_id": "message_1", "quote": "The team accepts Redis", "supports_claim": True}]}]),
        response([{"proposal_id": "proposal_0001", "proposal": "Use Redis", "status": "rejected",
                   "outcome_basis": "individual_opinion", "outcome_evidence": [
                       {"segment_id": "message_2", "quote": "I oppose Redis", "supports_claim": True}]}]),
    ])
    result = DecisionExtractor(provider, chunk_size=1).extract([
        msg(1, "The team accepts Redis"), msg(2, "I oppose Redis")])
    assert result[0].status == "accepted"
    assert result[0].outcome_basis == "explicit_acceptance"
    assert len(result[0].history) == 1


def test_multiple_objections_without_final_decision_remain_unresolved():
    objections = [
        {"segment_id": "message_1", "quote": "I object to using Redis", "supports_claim": True},
        {"segment_id": "message_2", "quote": "I also oppose this approach", "supports_claim": True},
    ]
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Use Redis", "status": "rejected", "outcome_basis": "explicit_rejection",
        "outcome_evidence": objections,
    }])])).extract([
        msg(1, "I object to using Redis", "A"), msg(2, "I also oppose this approach", "B")])
    assert result[0].status == "unresolved"
    assert result[0].outcome_basis == "unresolved"
    assert result[0].history == []


def test_denial_of_consensus_does_not_create_project_outcome():
    quote = "There is no consensus to reject the proposal."
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Use Redis", "status": "rejected", "outcome_basis": "consensus",
        "outcome_evidence": [{"segment_id": "message_1", "quote": quote, "supports_claim": True}],
    }])])).extract([msg(1, quote)])
    assert result[0].status == "unresolved"
    assert result[0].outcome_basis == "unresolved"
    assert result[0].history == []


def test_congratulations_do_not_create_decision_history_events():
    provider = MockProvider([
        response([{"proposal": "Use PostgreSQL", "status": "accepted",
                   "outcome_basis": "explicit_acceptance", "outcome_evidence": [
                       {"segment_id": "message_1", "quote": "The team accepts PostgreSQL", "supports_claim": True}]}]),
        response([{"proposal_id": "proposal_0001", "proposal": "Use PostgreSQL",
                   "status": "accepted", "outcome_basis": "explicit_acceptance",
                   "outcome_evidence": [{"segment_id": "message_2", "quote": "Congratulations, well done", "supports_claim": True}],
                   "history": [{"segment_id": "message_2", "status": "accepted", "outcome_basis": "explicit_acceptance"}]}]),
    ])
    result = DecisionExtractor(provider, chunk_size=1).extract([
        msg(1, "The team accepts PostgreSQL"), msg(2, "Congratulations, well done")])
    assert len(result[0].history) == 1
    assert result[0].history[0]["segment_id"] == "message_1"
    assert any(e.quote == "Congratulations, well done" for e in result[0].evidence)


def test_outcome_changing_message_creates_a_decision_history_event():
    provider = MockProvider([
        response([{"proposal": "Use Redis", "status": "unresolved", "outcome_basis": "unresolved"}]),
        response([{"proposal_id": "proposal_0001", "proposal": "Use Redis",
                   "status": "rejected", "outcome_basis": "explicit_rejection",
                   "outcome_evidence": [{"segment_id": "message_2",
                                         "quote": "The team has decided to reject Redis", "supports_claim": True}]}]),
    ])
    result = DecisionExtractor(provider, chunk_size=1).extract([
        msg(1, "We are considering Redis"), msg(2, "The team has decided to reject Redis")])
    assert result[0].status == "rejected"
    assert len(result[0].history) == 1
    assert result[0].history[0] == {
        "segment_id": "message_2", "status": "rejected", "outcome_basis": "explicit_rejection"}


def test_rejection_reasons_are_multiple_and_independently_verified():
    provider = MockProvider([response([{
        "proposal": "Use SQLite", "status": "rejected", "outcome_basis": "explicit_rejection",
        "outcome_evidence": [{"segment_id": "message_1", "quote": "We reject SQLite", "supports_claim": True}],
        "rejection_reasons": [
            {"text": "concurrent writes", "evidence": [{"segment_id": "message_1", "quote": "concurrent writes", "supports_claim": True}]},
            {"text": "replication", "evidence": [{"segment_id": "message_1", "quote": "no replication", "supports_claim": True}]},
        ]}])])
    result = DecisionExtractor(provider).extract([msg(1, "We reject SQLite for concurrent writes and no replication")])
    assert len(result[0].rejection_reasons) == 2
    assert all(reason.evidence[0].quote_verified for reason in result[0].rejection_reasons)


def test_rejection_without_stated_reason_has_explicitly_empty_reason_list():
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Use SQLite", "status": "rejected", "outcome_basis": "explicit_rejection",
        "outcome_evidence": [{"segment_id": "message_1", "quote": "We reject SQLite", "supports_claim": True}],
    }])])).extract([msg(1, "We reject SQLite")])
    assert result[0].rejection_reasons == []
    assert result[0].reason is None


def test_conflicting_opinions_and_unsupported_outcome_claim_stay_unresolved():
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Use Cassandra", "status": "accepted", "outcome_basis": "consensus",
        "outcome_evidence": [{"segment_id": "message_1", "quote": "I prefer Cassandra", "supports_claim": False}],
    }])])).extract([msg(1, "I prefer Cassandra, but others disagree")])
    assert result[0].status == "unresolved"
    assert result[0].outcome_basis == "unresolved"
    assert result[0].outcome_evidence == []
    assert result[0].evidence[0].supports_claim is None


def test_missing_author_timestamp_and_quote_presence_are_separate_from_support():
    source = DiscussionMessage(message_id="message_1", content="The team accepts PostgreSQL")
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Use PostgreSQL", "status": "accepted", "outcome_basis": "explicit_acceptance",
        "outcome_evidence": [{"segment_id": "message_1", "quote": "The team accepts PostgreSQL", "supports_claim": False}],
    }])])).extract([source])
    evidence = result[0].evidence[0]
    assert evidence.quote_verified is True
    assert evidence.supports_claim is False
    assert evidence.author is None and evidence.timestamp is None


def test_neutral_discussion_quote_has_unknown_support_assessment():
    text = "The syntax uses two colons."
    result = DecisionExtractor(MockProvider([response([{
        "proposal": "Use colon-based range syntax", "status": "unresolved",
        "outcome_basis": "unknown", "evidence": [
            {"segment_id": "message_1", "quote": text, "supports_claim": True}],
    }])])).extract([msg(1, text)])
    assert result[0].evidence[0].quote_verified is True
    assert result[0].evidence[0].supports_claim is None


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
