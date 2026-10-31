
import re
from typing import List
from app.core.schemas import DiscussionMessage


def parse_discussion(text: str) -> List[DiscussionMessage]:
    """
    Parse a simple transcript into chronological messages.

    Supported format:
    Author: message content

    Blank lines separate messages.
    """

    messages = []
    blocks = re.split(r"\n\s*\n", text.strip())

    for index, block in enumerate(blocks, start=1):
        block = block.strip()

        if not block:
            continue

        match = re.match(r"^([^:\n]{1,80}):\s*(.*)$", block, re.DOTALL)

        if match:
            author = match.group(1).strip()
            content = match.group(2).strip()
        else:
            author = "Unknown"
            content = block

        if content:
            messages.append(
                DiscussionMessage(
                    message_id="message_{}".format(index),
                    author=author,
                    content=content
                )
            )

    return messages
