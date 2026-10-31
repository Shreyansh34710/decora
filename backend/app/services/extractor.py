import json
import re
from typing import Dict, List, Optional

from pydantic import ValidationError

from app.ai.ollama_provider import OllamaProvider
from app.core.schemas import Alternative, DiscussionMessage, Evidence
from app.services.chunker import create_chunks
from app.services.evidence import verify_evidence


class DecisionExtractor:
    """Extract decisions chronologically while carrying proposals between chunks."""

    def __init__(self, provider=None, chunk_size=12):
        self.provider = provider or OllamaProvider()
        self.chunk_size = chunk_size

    @staticmethod
    def _parse_response(raw: str) -> List[dict]:
        if not raw or not raw.strip():
            raise RuntimeError("Model returned an empty extraction response")
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Model returned malformed JSON: {}".format(exc)) from exc
        if not isinstance(value, dict) or not isinstance(value.get("decisions"), list):
            raise RuntimeError("Model response must contain a decisions array")
        if not all(isinstance(item, dict) for item in value["decisions"]):
            raise RuntimeError("Model decisions must be JSON objects")
        return value["decisions"]

    @staticmethod
    def _key(proposal: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", proposal.lower()))

    @staticmethod
    def _prompt(registry: Dict[str, dict], chunk: List[DiscussionMessage],
                number: int, total: int) -> str:
        discussion = [{
            "message_id": message.message_id,
            "author": message.author,
            "timestamp": message.timestamp,
            "source_url": message.source_url,
            "content": message.content,
        } for message in chunk]
        return """You recover engineering decisions from a discussion. Process this new segment chronologically and update the persistent proposal registry. Keep one registry item for the same concrete technical choice only when the evidence makes the identity clear. Do not merge merely similar proposals. Do not invent claims, reasons, authors, timestamps, URLs, or quotes. A person's opinion alone is not a team decision. Use unresolved when outcome is unclear, contested when participants conflict and no resolution exists. Cite exact substrings from original message content and their message IDs. Return only JSON matching {\"decisions\":[{\"proposal\":string,\"status\":\"accepted|rejected|unresolved|contested\",\"reason\":string|null,\"outcome_basis\":\"explicit_acceptance|explicit_rejection|consensus|individual_opinion|unresolved|unknown\",\"evidence\":[{\"segment_id\":string,\"quote\":string}]}]}. Include all proposals in the registry, updating prior outcomes and accumulating evidence. If there are no proposals, return an empty array. This is chunk %d of %d.\n\nPERSISTENT PROPOSAL REGISTRY:\n%s\n\nNEW MESSAGES:\n%s""" % (
            number, total,
            json.dumps(list(registry.values()), ensure_ascii=False),
            json.dumps(discussion, ensure_ascii=False),
        )

    def extract(self, messages: List[DiscussionMessage]) -> List[Alternative]:
        chunks = create_chunks(messages, chunk_size=self.chunk_size)
        registry: Dict[str, dict] = {}

        for number, chunk in enumerate(chunks, start=1):
            raw = self.provider.generate(self._prompt(registry, chunk, number, len(chunks)))
            extracted = self._parse_response(raw)
            for item in extracted:
                proposal = item.get("proposal")
                if not isinstance(proposal, str) or not proposal.strip():
                    continue
                key = self._key(proposal)
                if not key:
                    continue
                try:
                    validated = Alternative(
                        decision_id="proposal_{}".format(key.replace(" ", "_")),
                        proposal=proposal.strip(),
                        status=item.get("status"),
                        reason=item.get("reason"),
                        outcome_basis=item.get("outcome_basis", "unknown"),
                        evidence=[Evidence(**e) for e in item.get("evidence", [])],
                    ).model_dump()
                except (ValidationError, TypeError) as exc:
                    raise RuntimeError("Model returned an invalid decision: {}".format(exc)) from exc

                previous = registry.get(key)
                if previous:
                    evidence = previous["evidence"] + [
                        e for e in validated["evidence"]
                        if e not in previous["evidence"]
                    ]
                    validated["evidence"] = evidence
                registry[key] = validated

        decisions = list(registry.values())
        if messages and not decisions:
            # Empty extraction is a valid inference result, distinct from model errors.
            return []
        return verify_evidence([Alternative(**item) for item in decisions], messages)
