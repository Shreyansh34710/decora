"""Live integration checks: RUN_OLLAMA_TEST=1 python -m pytest backend/tests/test_ollama.py -v"""
import os
import json

import httpx

import pytest

from app.ai.ollama_provider import OllamaProvider
from app.services.extractor import DecisionExtractor
from app.services.parser import parse_discussion


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_TEST") != "1",
    reason="set RUN_OLLAMA_TEST=1 to run live Qwen3 integration tests",
)


def _require_model(provider):
    try:
        response = httpx.get(provider.base_url + "/api/tags", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.fail("Ollama is unavailable at {}: {}. Start Ollama and retry.".format(
            provider.base_url, exc))
    models = response.json().get("models", [])
    names = [model.get("name", "") for model in models]
    if not any(name == provider.model or name.startswith(provider.model + ":")
               for name in names):
        pytest.fail("Ollama is reachable but model {!r} is not installed. Available: {}".format(
            provider.model, ", ".join(names) or "none"))


def test_ollama_generates_json_response():
    provider = OllamaProvider()
    _require_model(provider)
    result = provider.generate(
        'Return JSON only: {"status":"working"}'
    )
    parsed = json.loads(result)
    assert parsed["status"].lower() == "working"


def test_live_extraction_api_semantics_and_exact_evidence():
    provider = OllamaProvider()
    _require_model(provider)
    discussion = """Alice: I propose using MongoDB for our application.

Bob: I disagree because our data has complex relational dependencies.

Charlie: PostgreSQL would be a better choice for maintaining relational consistency.

Alice: After considering the discussion, I agree that PostgreSQL is the better option.

Bob: We should reject MongoDB for this project because our data relationships require relational consistency."""
    messages = parse_discussion(discussion)
    decisions = DecisionExtractor(provider).extract(messages)
    by_name = {d.proposal.lower(): d for d in decisions}
    mongo = next((d for name, d in by_name.items() if "mongodb" in name), None)
    postgres = next((d for name, d in by_name.items() if "postgresql" in name), None)
    assert mongo is not None, "Model did not extract MongoDB proposal: {}".format(decisions)
    assert mongo.status == "rejected", "MongoDB result was {}".format(mongo.model_dump())
    assert postgres is not None, "Model did not extract PostgreSQL proposal: {}".format(decisions)
    assert postgres.status == "accepted", "PostgreSQL result was {}".format(postgres.model_dump())
    for decision in (mongo, postgres):
        assert decision.verified
        assert decision.evidence
        for evidence in decision.evidence:
            original = next(m for m in messages if m.message_id == evidence.segment_id)
            assert evidence.quote in original.content


def test_live_cross_chunk_proposal_resolution():
    provider = OllamaProvider(num_predict=1800)
    _require_model(provider)
    lines = [
        "Alice: I propose using MongoDB for this application.",
        "Bob: What are our data access patterns?",
        "Charlie: We should document the core entities first.",
        "Alice: The first entity is an organization.",
        "Bob: Organizations have many projects.",
        "Charlie: Projects have tasks and owners.",
        "Alice: Owners can belong to multiple projects.",
        "Bob: Some tasks also depend on other tasks.",
        "Charlie: Those relationships need integrity checks.",
        "Alice: We should compare database options.",
        "Bob: MongoDB would need application-level relationship handling.",
        "Charlie: Let's evaluate PostgreSQL too.",
        "Alice: PostgreSQL supports relational constraints.",
        "Bob: We need migrations for schema changes.",
        "Charlie: Both options can be backed up.",
        "Alice: The API will query projects and tasks together.",
        "Bob: Consistent transactions matter for task updates.",
        "Charlie: PostgreSQL fits these relational queries.",
        "Alice: We should record the tradeoffs.",
        "Bob: MongoDB could still be useful for unrelated document data.",
        "Charlie: This application needs a single primary store.",
        "Alice: Our current scope is relational project data.",
        "Bob: We should choose based on that scope.",
        "Charlie: PostgreSQL is my recommendation.",
        "Alice: I support PostgreSQL for the project.",
        "Bob: The decision should reflect the relationship requirements.",
        "Charlie: We can revisit if requirements change.",
        "Alice: Let's finalize the database choice.",
        "Bob: We should reject MongoDB because complex relationships need relational consistency.",
        "Charlie: Agreed, use PostgreSQL as the primary database.",
    ]
    messages = parse_discussion("\n\n".join(lines))
    assert len(messages) >= 25
    assert len(messages[:12]) == 12
    decisions = DecisionExtractor(provider).extract(messages)
    mongo = next((d for d in decisions if "mongodb" in d.proposal.lower()), None)
    postgres = next((d for d in decisions if "postgresql" in d.proposal.lower()), None)
    assert mongo is not None and mongo.status == "rejected", decisions
    assert postgres is not None and postgres.status == "accepted", decisions
    assert any(e.segment_id == "message_1" for e in mongo.evidence)
    assert any(e.segment_id in ("message_29", "message_30") for e in mongo.evidence)
    assert all(d.verified for d in (mongo, postgres))
