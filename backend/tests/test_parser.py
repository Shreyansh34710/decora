
from app.services.parser import parse_discussion
from app.services.chunker import create_chunks


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
