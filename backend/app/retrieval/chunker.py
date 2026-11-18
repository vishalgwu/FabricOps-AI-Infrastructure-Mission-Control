"""Split Markdown into chunks at headings and paragraph boundaries, with stable chunk IDs.

Chunk ID format:  <document_id>:<version>:<section-slug>:<n>
  - the version is part of the ID, so a citation always pins the exact document version;
  - <n> is the position of the chunk inside its section (0, 1, ...). Re-chunking identical
    text always gives identical IDs. Editing a section may renumber that section's chunks.
"""
import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 800
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_NOTICE = re.compile(r"^>\s*SYNTHETIC", re.IGNORECASE)


@dataclass(frozen=True)
class RawChunk:
    chunk_index: int
    section: str
    slug: str
    text: str


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    parts, current = [], ""
    for word in paragraph.split():
        if current and len(current) + 1 + len(word) > max_chars:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_markdown(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[RawChunk]:
    # 1. Walk the lines, tracking the heading path and collecting paragraphs per section.
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = []  # (section label, paragraphs)
    paragraph: list[str] = []

    def label() -> str:
        names = [name for level, name in stack if level > 1]
        return " > ".join(names) if names else "Overview"

    def flush() -> None:
        if not paragraph:
            return
        body = " ".join(line.strip() for line in paragraph).strip() if not any(
            ln.lstrip().startswith(("-", "*", "1.")) for ln in paragraph
        ) else "\n".join(line.rstrip() for line in paragraph).strip()
        paragraph.clear()
        if not body or _NOTICE.match(body):
            return  # the synthetic-labelling notice is metadata, not retrievable content
        name = label()
        if not sections or sections[-1][0] != name:
            sections.append((name, []))
        sections[-1][1].append(body)

    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2)))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line)
    flush()

    # 2. Pack paragraphs of a section into chunks of at most max_chars.
    chunks: list[RawChunk] = []
    for name, paragraphs in sections:
        pieces: list[str] = []
        for p in paragraphs:
            pieces.extend(_split_long(p, max_chars) if len(p) > max_chars else [p])
        packed: list[str] = []
        current = ""
        for piece in pieces:
            if current and len(current) + 2 + len(piece) > max_chars:
                packed.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}".strip() if current else piece
        if current:
            packed.append(current)
        slug = slugify(name)
        for i, body in enumerate(packed):
            chunks.append(RawChunk(i, name, slug, body))
    return chunks


def chunk_id(document_id: str, version: str, slug: str, index: int) -> str:
    return f"{document_id}:{version}:{slug}:{index}"
