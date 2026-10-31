from typing import List

from app.core.schemas import Alternative, DiscussionMessage, Evidence


def verify_evidence(decisions: List[Alternative],
                    messages: List[DiscussionMessage]) -> List[Alternative]:
    """Retain only exact source quotations; this checks provenance, not entailment."""
    message_map = {message.message_id: message for message in messages}
    for decision in decisions:
        valid_evidence = []
        for evidence in decision.evidence:
            original = message_map.get(evidence.segment_id)
            quote = evidence.quote.strip()
            if original is not None and quote and quote in original.content:
                valid_evidence.append(Evidence(
                    segment_id=evidence.segment_id,
                    quote=quote,
                    author=original.author,
                    timestamp=original.timestamp,
                    source_url=original.source_url,
                ))
        decision.evidence = valid_evidence
        decision.verified = bool(valid_evidence)
    return decisions
