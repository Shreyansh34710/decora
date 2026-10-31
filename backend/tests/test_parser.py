
from app.services.parser import parse_discussion
from app.services.chunker import create_chunks
from pathlib import Path


def test_parser_extracts_messages():
    text = """
Alice: We should use PostgreSQL.

Bob: MongoDB may be easier to scale.

Alice: PostgreSQL provides the relational structure we need.
"""

    messages = parse_discussion(text)

    assert len(messages) == 3
    assert messages[0].author == "Alice"
    assert messages[1].author == "Bob"


def test_chunking_preserves_order():
    text = "\n\n".join(
        "User{}: Message {}".format(i, i)
        for i in range(25)
    )

    messages = parse_discussion(text)
    chunks = create_chunks(messages, chunk_size=10)

    assert len(chunks) == 3
    assert len(chunks[0]) == 10
    assert len(chunks[1]) == 10
    assert len(chunks[2]) == 5

    assert chunks[0][0].author == "User0"
    assert chunks[2][-1].author == "User24"


def test_seven_consecutive_speaker_prefixed_messages_are_segmented_in_order():
    text = "\n".join([
        "Guido van Rossum: First message.",
        "ZHUO QL (KDr2): Second message.",
        "Chris Jerdonek: Third message.",
        "Random832: Fourth message.",
        "Chris Angelico: Fifth message.",
        "Guido van Rossum: Sixth message.",
        "Nick Coghlan: Seventh message.",
    ])

    messages = parse_discussion(text)

    assert len(messages) == 7
    assert [message.author for message in messages] == [
        "Guido van Rossum", "ZHUO QL (KDr2)", "Chris Jerdonek", "Random832",
        "Chris Angelico", "Guido van Rossum", "Nick Coghlan",
    ]
    assert [message.content for message in messages] == [
        "First message.", "Second message.", "Third message.", "Fourth message.",
        "Fifth message.", "Sixth message.", "Seventh message.",
    ]


def test_multiline_message_body_stays_with_its_speaker():
    messages = parse_discussion(
        "Alice: First line.\nContinuation with a colon: still body.\n"
        "And a final line.\nBob: Next message."
    )

    assert len(messages) == 2
    assert messages[0].author == "Alice"
    assert messages[0].content == (
        "First line.\nContinuation with a colon: still body.\nAnd a final line."
    )
    assert messages[1].author == "Bob"


def test_blank_lines_between_messages_and_repeated_speakers_are_preserved():
    messages = parse_discussion("Alice: First.\n\n\nBob: Reply.\n\nAlice: Follow-up.")

    assert [(message.author, message.content) for message in messages] == [
        ("Alice", "First."), ("Bob", "Reply."), ("Alice", "Follow-up."),
    ]


def test_punctuation_and_colons_in_body_do_not_create_boundaries():
    messages = parse_discussion(
        "Alice: We tried v1.2, but it failed: timeouts, retries, etc.\n"
        "The next sentence has a colon: it remains in Alice's message.\n"
        "Bob: Agreed!"
    )

    assert len(messages) == 2
    assert "failed: timeouts" in messages[0].content
    assert "colon: it remains" in messages[0].content
    assert messages[1].content == "Agreed!"


def test_quoted_reply_is_retained_as_context_not_a_new_message():
    messages = parse_discussion(
        "Alice: I disagree with the earlier proposal.\n"
        "> Bob: We should keep the old behavior.\n"
        "The quoted rationale matters.\n"
        "Carol: I agree with Alice."
    )

    assert len(messages) == 2
    assert messages[0].author == "Alice"
    assert "> Bob: We should keep the old behavior." in messages[0].content
    assert "The quoted rationale matters." in messages[0].content


def test_ambiguous_prose_colon_does_not_invent_speakers_or_boundaries():
    text = "In short: this is prose, not a speaker.\nPerhaps the conclusion is unclear."

    messages = parse_discussion(text)

    assert len(messages) == 1
    assert messages[0].author == "Unknown"
    assert messages[0].content == text


def test_pep_572_transcript_remains_seven_messages_with_attribution():
    sample = Path(__file__).resolve().parents[2] / "examples" / "pep_evaluation" / "pep572_assignment_expressions.txt"

    messages = parse_discussion(sample.read_text(encoding="utf-8"))

    assert len(messages) == 7
    assert [message.author for message in messages] == [
        "Guido van Rossum", "ZHUO QL (KDr2)", "Chris Jerdonek", "Random832",
        "Chris Angelico", "Guido van Rossum", "Nick Coghlan",
    ]
