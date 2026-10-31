
from typing import List
from app.core.schemas import DiscussionMessage


def create_chunks(
    messages: List[DiscussionMessage],
    chunk_size: int = 12
) -> List[List[DiscussionMessage]]:
    """
    Split messages into chronological chunks.
    Message order is preserved.
    """

    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")

    return [
        messages[index:index + chunk_size]
        for index in range(0, len(messages), chunk_size)
    ]
