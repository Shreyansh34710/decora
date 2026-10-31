# PEP mailing-list decision recovery evaluation

**Result: FAIL for reliable decision recovery; partial capability demonstrated.**

## Source and selection

Selected the public Python-Dev archive thread [“Accepting PEP 572, Assignment Expressions”](https://mail.python.org/archives/list/python-dev@python.org/thread/J6EBK6ZEHZXTVWYSUO5N5XCUS45UQSB3/). The thread is a useful bounded case because its first post contains an explicit project-level acceptance, while later posts discuss a proposed extension (assignment to attributes and subscripts) and give reasons against it. It also includes a question and congratulatory replies, allowing a check that individual comments are not confused with decisions.

The public HTML thread displayed seven posts and was readable. Its downloadable mbox export returned HTTP 403, so the input transcript was prepared from the post bodies visible in the archive thread view. Repeated quoted reply chains, signatures, footer text, and references/links to the PEP document were omitted. The resulting transcript preserves the seven-post chronology and author attribution; it is a source-derived transcript, not a byte-for-byte mbox export.

The PEP document itself was not opened as extraction input and was not sent to the model. The input contains only mailing-list message text, including the thread's mention of “PEP 572” and the feature name. It contains no PEP document body, document URL, or document-derived summary.

Files:

- Input: [`pep572_assignment_expressions.txt`](pep572_assignment_expressions.txt)
- Actual API response: [`pep572_assignment_expressions_output.json`](pep572_assignment_expressions_output.json)
- Public source: https://mail.python.org/archives/list/python-dev@python.org/thread/J6EBK6ZEHZXTVWYSUO5N5XCUS45UQSB3/

## Procedure

Two bounded requests were made to Decora's existing `POST /api/extract` route using FastAPI `TestClient`: an initial run, then one rerun after correcting the transcript to preserve the archive's exact spelling. The saved JSON is the response from the corrected input. The application constructed its configured `OllamaProvider`; the response reports model `qwen3:8b`. No other inference provider was used.

Equivalent local invocation from the repository root:

```python
import sys
sys.path.insert(0, "backend")
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

text = Path("examples/pep_evaluation/pep572_assignment_expressions.txt").read_text()
response = TestClient(app).post("/api/extract", json={
    "title": "Accepting PEP 572, Assignment Expressions (mailing-list thread only)",
    "text": text,
})
response.raise_for_status()
```

The returned JSON was saved without manual edits. The endpoint returned HTTP 200, `total_messages: 7`, and two decisions marked verified.

## Findings against the messages

Archive-displayed dates/times and generated message IDs:

| ID | Author | Archive-displayed timestamp |
| --- | --- | --- |
| message_1 | Guido van Rossum | July 12, 2018, 12:10 a.m. |
| message_2 | ZHUO QL (KDr2) | July 12, 2018, 7:37 a.m. |
| message_3 | Chris Jerdonek | July 12, 2018, 10:06 a.m. |
| message_4 | Random832 | July 13, 2018, 1:36 p.m. |
| message_5 | Chris Angelico | July 13, 2018, 1:55 p.m. |
| message_6 | Guido van Rossum | July 13, 2018, 2:50 p.m. |
| message_7 | Nick Coghlan | July 15, 2018, 5:32 a.m. |

The archive view does not state a timezone for these displayed times; none is inferred. The transcript parser accepted the authors and chronological order but does not parse timestamps or source URLs into message metadata. Consequently, output evidence has correct author names but `timestamp: null` and `source_url: null`.

### Verified findings

- **Accepted proposal:** Correctly identified “Accept PEP 572, Assignment Expressions” as accepted, with `explicit_acceptance`. Its quote from message_1 (“As anticippated, after a final round of feedback I am hereby accepting PEP 572, Assignment Expressions.”) is an exact substring of the saved input and is correctly attributed to Guido van Rossum. The archive itself displays the typo “anticippated”; the transcript and model quote retain it.
- **Rejection reasons recovered:** “Not enough use cases” is supported by Guido's message_6, “Also nobody had a use case.” “Potential reduction in code clarity” is supported by Nick Coghlan's message_7, which says the design decision was that allowing it would reduce clarity.
- **Proposal identity:** The model kept acceptance of PEP 572 separate from the proposal to allow attribute/subscript targets. It did not merge the two outcomes.
- **Quote presence:** Every quote retained in the JSON occurs verbatim in its cited message text in the saved input. Quote presence is verified; this does not mean each quote logically supports the attached claim.

### Ambiguous findings

- **Extension outcome:** The replies strongly support that maintainers did not want assignment to attributes/subscripts in the feature as discussed: Chris Angelico says the broad target rule was “not desired,” Guido says there was no use case, and Nick Coghlan describes a design decision against it. However, this thread does not contain an explicit final statement such as “this extension is rejected.” Calling the result rejected is a defensible inference; classifying it as `explicit_rejection` overstates the source. `consensus` or `unresolved` would need careful review; the evidence most strongly suggests an informal maintainer position rather than a formal ruling in this thread.
- The seven-message thread is a narrow final-acceptance thread, not the full historical PEP 572 debate. It evaluates extraction from this accessible discussion only.

### Extraction errors

- **Unsupported outcome evidence:** The output cites Random832's message_4 question (“Why does this not allow assignment to attributes and subscripts?”) as supporting rejection and sets `supports_claim: true`. A question establishes that the behavior was queried; it does not support that the proposal was rejected. The quote is present, but the support label is wrong.
- **Reason omission:** Chris Angelico's message_5 gives an additional reason: arbitrary targets would also permit iterable unpacking, “which is not desired.” The output quotes part of that message but does not include this reason in `rejection_reasons`. It therefore misses one of the thread's clearest technical rationales.
- **Overconfident basis:** The extension is marked `explicit_rejection` despite no explicit final rejection statement in the thread.
- **History contamination:** The accepted proposal's history records messages 2 and 3 as accepted decision events. Those messages are congratulations/reactions, not new project decisions. The rejected extension's history similarly records each rationale post as a rejection event. The final statuses happen to be plausible, but these per-message decision-history classifications are not source-faithful.
- **Evidence category leakage:** The response copies rationale and even the question into `outcome_evidence`, mixing evidence for outcome with evidence for reasons. This conflicts with the requested distinction. The service verifies substring presence but does not independently validate `supports_claim`; the JSON's `verified: true` confirms provenance only.

## Conclusion and limits

Decora passes the basic direct-acceptance case and recovers two actual reasons against a technically distinct extension. It fails the stricter evaluation because it overstates an inferred outcome as explicit, assigns logical support to a non-supporting question, omits a stated reason, and treats reactions/rationale messages as decision-history events. Evidence verification is lexical, not semantic.

This is one short, source-derived thread and one successful Qwen3:8b run, not a general benchmark. The parser's `Author: text` format cannot carry timestamps or source URLs into output metadata. The mbox export was inaccessible, and the transcript is a cleaned rendering of the public HTML post bodies rather than a raw archive export. No algorithm or product code was changed during this evaluation.

## Focused post-fix regression

After the reliability changes, one additional bounded Qwen3:8b request used the same saved transcript. Its unedited response is in [`pep572_assignment_expressions_output_after_fix.json`](pep572_assignment_expressions_output_after_fix.json).

The documented errors improved in this run:

- PEP 572 remains accepted from Guido's direct acceptance statement.
- The attribute/subscript extension is `unresolved`, not `explicit_rejection`, because no clear final rejection statement appears in the supplied messages.
- Random832's question is retained as general discussion evidence with `supports_claim: null`; it is absent from `outcome_evidence`.
- Only the direct acceptance message creates a history event. The congratulatory, question, and rationale messages do not.
- Four distinct reason entries are present, each with its own quote: lack of use cases, reduced clarity, iterable unpacking being undesirable, and helper-function alternatives. The legacy scalar `reason` remains a joined summary; `rejection_reasons` is the separate evidence-bearing list.

This single post-fix run addresses the four observed PEP-thread failures. It does not establish general accuracy. `supports_claim` remains a model assessment; lexical gates reject obvious questions/reactions and require direct outcome wording for accepted/rejected status, but they cannot prove entailment for arbitrary prose. Quote verification still checks source presence only.
