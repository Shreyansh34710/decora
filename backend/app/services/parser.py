
import re
from typing import List
from app.core.schemas import DiscussionMessage


# Keep this deliberately narrower than ``[^:]+``. A colon in prose (for
# example, ``In short: ...``) is not enough evidence to invent a speaker.
_SPEAKER_PREFIX = re.compile(
    r"^\s*([\w][\w .@()'’\-]{0,79}):(?:\s*)(.*)$", re.UNICODE
)
_PROSE_LABELS = {
    "answer", "context", "example", "important", "in short", "note",
    "question", "summary", "therefore", "however", "for example",
}
_NAME_PARTICLES = {"da", "de", "del", "der", "di", "du", "la", "le", "van", "von"}


def _speaker_header(line: str):
    """Return (author, first body line) for a plausible speaker-prefixed line."""
    # Quoted lines are context, not message boundaries. Keep them in the body.
    if line.lstrip().startswith((">", "|")):
        return None
    match = _SPEAKER_PREFIX.match(line)
    if not match:
        return None
    author = match.group(1).strip()
    # Reject labels that read like sentence fragments or contain markup.
    if (not author or author[-1:] in ".!?" or "  " in author
            or author.casefold() in _PROSE_LABELS):
        return None
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", author)
    if len(words) > 1 and any(
            not (word[0].isupper() or word.isupper() or word.casefold() in _NAME_PARTICLES)
            for word in words):
        return None
    return author, match.group(2)


def parse_discussion(text: str) -> List[DiscussionMessage]:
    """
    Parse a simple transcript into chronological messages.

    Supported format:
    Author: message content

    Blank lines separate messages.
    """

    if not text or not text.strip():
        return []

    lines = text.strip().splitlines()
    headers = [_speaker_header(line) for line in lines]

    # Treat repeated, line-leading speaker prefixes as message boundaries.
    # Requiring more than one header avoids turning an isolated prose label
    # such as "Note: ..." into a fabricated conversation.
    if sum(header is not None for header in headers) >= 2:
        messages = []
        author = None
        body = []

        def append_message():
            content = "\n".join(body).strip()
            if content:
                messages.append(DiscussionMessage(
                    message_id="message_{}".format(len(messages) + 1),
                    author=author or "Unknown",
                    content=content,
                ))

        for line, header in zip(lines, headers):
            if header is not None:
                append_message()
                author, first_line = header
                body = [first_line] if first_line else []
            elif author is not None:
                body.append(line)
            elif line.strip():
                # Preserve any preamble instead of silently dropping it.
                body.append(line)
        append_message()
        return messages

    # Keep the established blank-line behavior for ordinary and legacy input.
    messages = []
    blocks = re.split(r"\n\s*\n", text.strip())

    for index, block in enumerate(blocks, start=1):
        block = block.strip()

        if not block:
            continue

        header = _speaker_header(block.splitlines()[0])

        if header:
            author, first_line = header
            content = "\n".join([first_line] + block.splitlines()[1:]).strip()
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
