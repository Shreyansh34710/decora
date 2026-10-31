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


def deduplicate_evidence(items, reduce_contained=False):
    """Remove repeated quotes, and optionally contained outcome excerpts."""
    result = []
    exact = {}
    for evidence in items:
        key = (evidence.segment_id, evidence.quote)
        if key in exact:
            existing = result[exact[key]]
            if existing.supports_claim != evidence.supports_claim:
                existing.supports_claim = None
            continue
        if reduce_contained and evidence.supports_claim is True:
            contained = next((index for index, existing in enumerate(result)
                              if existing.segment_id == evidence.segment_id
                              and existing.supports_claim is True
                              and (existing.quote in evidence.quote
                                   or evidence.quote in existing.quote)), None)
            if contained is not None:
                existing = result[contained]
                if existing.quote in evidence.quote and existing.quote != evidence.quote:
                    del exact[(existing.segment_id, existing.quote)]
                    result[contained] = evidence
                    exact[key] = contained
                continue
        exact[key] = len(result)
        result.append(evidence)
    return result


def _verify(items, message_map, reduce_contained=False):
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
    return deduplicate_evidence(verified, reduce_contained=reduce_contained)


def verify_evidence(decisions: List[Alternative],
                    messages: List[DiscussionMessage]) -> List[Alternative]:
    """Retain only exact source quotations; this checks provenance, not entailment."""
    message_map = {message.message_id: message for message in messages}
    for decision in decisions:
        decision.evidence = _verify(decision.evidence, message_map)
        decision.outcome_evidence = _verify(
            decision.outcome_evidence, message_map, reduce_contained=True)
        for reason in decision.rejection_reasons:
            # Reasons are separate claims; only exact duplicates are redundant.
            reason.evidence = _verify(reason.evidence, message_map)
        decision.verified = any(
            evidence.quote_verified and evidence.supports_claim is True
            for evidence in decision.outcome_evidence)
    return decisions
