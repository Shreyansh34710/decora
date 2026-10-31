from typing import List

from app.core.schemas import Alternative, DiscussionMessage, Evidence


def normalize_support_assessment(quote: str, assessment):
    """Keep model support unknown for clear questions and social reactions."""
    text = quote.strip().lower()
    if "?" in text or text.startswith((
            "why ", "what ", "how ", "when ", "where ", "who ", "which ",
            "can ", "could ", "would ", "should ", "do ", "does ", "did ",
            "is ", "are ", "was ", "were ")):
        return None
    if any(marker in text for marker in ("congratulations", "congrats", "hooray", "well done")):
        return None
    return assessment if isinstance(assessment, bool) else None


def _verify(items, message_map):
    verified = []
    for evidence in items:
        original = message_map.get(evidence.segment_id)
        quote = evidence.quote.strip()
        present = original is not None and bool(quote) and quote in original.content
        if not present:
            continue
        verified.append(Evidence(
            segment_id=evidence.segment_id,
            quote=quote,
            author=original.author if original.author != "Unknown" else None,
            timestamp=original.timestamp,
            source_url=original.source_url,
            quote_verified=True,
            # Presence proves provenance only; entailment remains model-proposed.
            supports_claim=normalize_support_assessment(quote, evidence.supports_claim),
        ))
    return verified


def verify_evidence(decisions: List[Alternative],
                    messages: List[DiscussionMessage]) -> List[Alternative]:
    """Retain only exact source quotations; this checks provenance, not entailment."""
    message_map = {message.message_id: message for message in messages}
    for decision in decisions:
        decision.evidence = _verify(decision.evidence, message_map)
        decision.outcome_evidence = _verify(decision.outcome_evidence, message_map)
        for reason in decision.rejection_reasons:
            reason.evidence = _verify(reason.evidence, message_map)
        decision.verified = bool(decision.outcome_evidence or decision.evidence)
    return decisions
