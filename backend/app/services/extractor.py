import json
import re
from typing import Dict, List

from pydantic import ValidationError

from app.ai.ollama_provider import OllamaProvider
from app.core.schemas import Alternative, DiscussionMessage, Evidence, RejectionReason
from app.services.chunker import create_chunks
from app.services.evidence import verify_evidence


class DecisionExtractor:
    """Extract decisions chronologically while carrying a proposal registry."""

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
            "author": message.author if message.author != "Unknown" else None,
            "timestamp": message.timestamp,
            "source_url": message.source_url,
            "content": message.content,
        } for message in chunk]
        schema = {
            "decisions": [{
                "proposal_id": "existing registry id or null for a new proposal",
                "proposal": "canonical concrete technical choice",
                "status": "accepted|rejected|unresolved",
                "outcome_basis": "explicit_acceptance|explicit_rejection|consensus|individual_opinion|unresolved|unknown",
                "outcome_evidence": [{"segment_id": "...", "quote": "exact substring", "supports_claim": True}],
                "rejection_reasons": [{"text": "stated reason, or omit if none", "evidence": [{"segment_id": "...", "quote": "exact substring", "supports_claim": True}]}],
                "history": [{"segment_id": "...", "status": "...", "outcome_basis": "..."}]
            }]
        }
        return ("You recover engineering proposals and decisions from a raw technical discussion. "
                "Process messages chronologically. Reuse proposal_id for the same concrete choice, "
                "even when its wording changes; keep distinct choices separate even if similar. "
                "The registry includes the first-seen canonical wording and accumulated history. "
                "A proposal mentioned in a later message may refer to one much earlier; match only "
                "when evidence makes identity clear. An individual's view is not project acceptance "
                "or rejection. Classify it as individual_opinion with status unresolved unless the "
                "discussion establishes a project outcome. Silence is never an outcome. Preserve "
                "conflicting positions and use unresolved when there is no final resolution. "
                "Separate outcome_evidence from rejection reason evidence. Give every stated "
                "rejection reason separately; if none is stated, return an empty reason list. "
                "Never invent reasons, authors, timestamps, URLs, message IDs, or quotes. Quote exact "
                "substrings and mark supports_claim true only when the quote logically supports the "
                "specific claim; quote presence will be independently checked. Include metadata "
                "only as present in source messages. Include every proposal that should be in the "
                "registry and its newly observed history; do not repeat old history. Return JSON "
                "only following this shape: {}. Chunk {} of {}.\n\nREGISTRY:\n{}\n\nNEW MESSAGES:\n{}".format(
                    json.dumps(schema, ensure_ascii=False), number, total,
                    json.dumps(list(registry.values()), ensure_ascii=False),
                    json.dumps(discussion, ensure_ascii=False)) )

    @staticmethod
    def _evidence(records, chunk):
        messages = {m.message_id: m for m in chunk}
        result = []
        for entry in records or []:
            if not isinstance(entry, dict):
                continue
            message = messages.get(entry.get("segment_id"))
            result.append(Evidence(
                segment_id=str(entry.get("segment_id", "")),
                quote=str(entry.get("quote", "")),
                author=message.author if message else None,
                timestamp=message.timestamp if message else None,
                source_url=message.source_url if message else None,
                supports_claim=entry.get("supports_claim") if isinstance(entry.get("supports_claim"), bool) else None,
            ))
        return result

    def extract(self, messages: List[DiscussionMessage]) -> List[Alternative]:
        chunks = create_chunks(messages, chunk_size=self.chunk_size)
        registry: Dict[str, dict] = {}
        aliases: Dict[str, str] = {}
        counters = 0

        for number, chunk in enumerate(chunks, start=1):
            extracted = self._parse_response(self.provider.generate(
                self._prompt(registry, chunk, number, len(chunks))))
            for item in extracted:
                proposal = item.get("proposal")
                if not isinstance(proposal, str) or not proposal.strip():
                    continue
                proposal = proposal.strip()
                key = self._key(proposal)
                requested_id = item.get("proposal_id")
                identity = requested_id if isinstance(requested_id, str) and requested_id in registry else aliases.get(key)
                if identity is None:
                    counters += 1
                    identity = "proposal_{:04d}".format(counters)
                    registry[identity] = Alternative(
                        decision_id=identity, proposal=proposal, status="unresolved",
                        outcome_basis="unknown").model_dump()
                aliases[key] = identity

                try:
                    previous = Alternative(**registry[identity])
                    status = item.get("status", previous.status)
                    basis = item.get("outcome_basis", previous.outcome_basis)
                    evidence = self._evidence(item.get("outcome_evidence", item.get("evidence", [])), chunk)
                    reason_items = item.get("rejection_reasons")
                    if reason_items is None and item.get("reason"):
                        reason_items = [{"text": item["reason"], "evidence": item.get("reason_evidence", [])}]
                    new_reasons = [RejectionReason(
                        text=str(r.get("text", "")), evidence=self._evidence(r.get("evidence", []), chunk))
                        for r in (reason_items or []) if isinstance(r, dict) and r.get("text")]
                    history = list(previous.history)
                    new_history = item.get("history", [])
                    if not new_history and (evidence or status != previous.status or basis != previous.outcome_basis):
                        new_history = [{"segment_id": evidence[0].segment_id if evidence else None,
                                        "status": status, "outcome_basis": basis}]
                    history.extend(h for h in new_history if h not in history)
                    merged_evidence = list(previous.evidence)
                    merged_outcome = list(previous.outcome_evidence)
                    for candidate in evidence:
                        if candidate not in merged_evidence:
                            merged_evidence.append(candidate)
                        if candidate not in merged_outcome:
                            merged_outcome.append(candidate)
                    # Keep a model assertion of an outcome separate from its quote provenance.
                    if status in ("accepted", "rejected") and not merged_outcome and evidence:
                        status, basis = "unresolved", "unknown"
                    if (status in ("accepted", "rejected") and
                            any(e.supports_claim is False for e in evidence)):
                        status, basis = "unresolved", "unknown"
                    merged_reasons = list(previous.rejection_reasons)
                    for reason in new_reasons:
                        found = next((r for r in merged_reasons if r.text == reason.text), None)
                        if found:
                            found.evidence.extend(e for e in reason.evidence if e not in found.evidence)
                        else:
                            merged_reasons.append(reason)
                    # An individual opinion cannot overwrite a project outcome.
                    if basis == "individual_opinion" and previous.outcome_basis in ("explicit_acceptance", "explicit_rejection", "consensus"):
                        status, basis = previous.status, previous.outcome_basis
                    current = Alternative(
                        decision_id=identity, proposal=previous.proposal, status=status,
                        reason="; ".join(r.text for r in merged_reasons) or None,
                        outcome_basis=basis, evidence=merged_evidence,
                        outcome_evidence=merged_outcome, rejection_reasons=merged_reasons,
                        history=history,
                    )
                except (ValidationError, TypeError, AttributeError) as exc:
                    raise RuntimeError("Model returned an invalid decision: {}".format(exc)) from exc
                registry[identity] = current.model_dump()

        return verify_evidence([Alternative(**item) for item in registry.values()], messages)
