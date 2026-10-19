"""Text cleaning plus structure-aware recursive and semantic chunking."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

import numpy as np
from pydantic import BaseModel, Field

from .parsers import Block

Strategy = Literal["recursive", "semantic"]
EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


class ChunkingSettings(BaseModel):
    strategy: Strategy = "recursive"
    chunk_size: int = Field(1000, ge=100, le=8000, description="target characters per chunk")
    chunk_overlap: int = Field(150, ge=0, le=2000)
    # Semantic: split where adjacent-sentence distance exceeds this percentile.
    breakpoint_percentile: float = Field(90.0, ge=50, le=99)
    min_chunk_size: int = Field(200, ge=0)


@dataclass
class Chunk:
    text: str
    heading_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    index: int = 0

    def embedding_text(self, title: str | None = None, summary: str | None = None) -> str:
        """Text sent to the embedding model: document context + section path + chunk."""
        header = [p for p in (title, " > ".join(self.heading_path)) if p]
        prefix = "\n".join(header)
        if summary:
            prefix = f"{prefix}\n{summary}" if prefix else summary
        return f"{prefix}\n\n{self.text}" if prefix else self.text


# --------------------------------------------------------------------------- cleaning

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = CONTROL.sub("", text).replace("­", "").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def drop_running_headers(blocks: list[Block]) -> list[Block]:
    """Removes short lines repeated on most pages (running headers, footers, page numbers)."""
    pages = {b.page for b in blocks if b.page is not None}
    if len(pages) < 4:
        return blocks
    counts = Counter(
        re.sub(r"\d+", "#", b.text.strip())
        for b in {(b.page, b.text): b for b in blocks if b.page is not None and len(b.text) < 80}.values()
    )
    repeated = {text for text, n in counts.items() if n >= len(pages) * 0.6}
    return [b for b in blocks if not (len(b.text) < 80 and re.sub(r"\d+", "#", b.text.strip()) in repeated)]


# --------------------------------------------------------------------------- sections


@dataclass
class Section:
    heading_path: list[str]
    units: list[tuple[str, int | None]]  # (text, page) in order


def build_sections(blocks: list[Block]) -> list[Section]:
    sections: list[Section] = []
    path: list[tuple[int, str]] = []
    current = Section([], [])
    for block in blocks:
        text = clean_text(block.text)
        if not text:
            continue
        if block.kind == "heading":
            if current.units:
                sections.append(current)
            level = block.level or 1
            path = [p for p in path if p[0] < level] + [(level, text)]
            current = Section([t for _, t in path], [])
        else:
            current.units.append((text, block.page))
    if current.units:
        sections.append(current)
    return sections


# --------------------------------------------------------------------------- recursive

SEPARATORS = ["\n\n", "\n", ". ", "; ", ", ", " ", ""]


def split_recursive(text: str, size: int, overlap: int, separators: list[str] = SEPARATORS) -> list[str]:
    """LangChain-style recursive character splitter with overlap."""
    if len(text) <= size:
        return [text] if text.strip() else []
    sep = next((s for s in separators if s and s in text), "")
    rest = separators[separators.index(sep) + 1 :] if sep in separators else []
    pieces = text.split(sep) if sep else list(text)

    chunks: list[str] = []
    window: list[str] = []
    length = 0
    for piece in pieces:
        if len(piece) > size:
            if window:
                chunks.append(sep.join(window))
                window, length = [], 0
            chunks.extend(split_recursive(piece, size, overlap, rest or [""]))
            continue
        added = len(piece) + (len(sep) if window else 0)
        if length + added > size and window:
            chunks.append(sep.join(window))
            # Keep trailing pieces as overlap for the next chunk.
            while window and (length > overlap or length + added > size):
                length -= len(window[0]) + (len(sep) if len(window) > 1 else 0)
                window.pop(0)
            added = len(piece) + (len(sep) if window else 0)
        window.append(piece)
        length += added
    if window:
        chunks.append(sep.join(window))
    return [c.strip() for c in chunks if c.strip()]


def _overlap_tail(text: str, overlap: int) -> str:
    """The last `overlap` characters of a chunk, starting at a sentence or word boundary."""
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    if len(text) <= overlap:
        return text
    for boundary in (". ", "\n", "; ", ", ", " "):
        cut = tail.find(boundary)
        if cut != -1 and cut + len(boundary) < len(tail):
            return tail[cut + len(boundary) :].lstrip()
    return tail


def split_with_overlap(text: str, size: int, overlap: int) -> list[str]:
    """Recursive split where every chunk after the first repeats the end of the previous one.

    split_recursive alone only carries over whole pieces (paragraphs, sentences) that are
    shorter than the overlap, so with ordinary prose the overlap almost never happens.
    Here the base chunks are size - overlap long and get the previous chunk's tail
    prepended, so the overlap is always present and chunks never exceed `size`."""
    overlap = max(0, min(overlap, size // 2))
    base = split_recursive(text, size - overlap - 1, 0)  # -1 for the joining space
    chunks = base[:1]
    for previous, current in zip(base, base[1:]):
        tail = _overlap_tail(previous, overlap)
        chunks.append(f"{tail} {current}" if tail else current)
    return chunks


def _pages_of(text_units: list[tuple[str, int | None]]) -> tuple[int | None, int | None]:
    pages = [p for _, p in text_units if p is not None]
    return (min(pages), max(pages)) if pages else (None, None)


def chunk_recursive(sections: list[Section], settings: ChunkingSettings) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        # Track which page each character offset came from.
        text, spans, offset = "", [], 0
        for unit, page in section.units:
            if text:
                text += "\n\n"
                offset += 2
            spans.append((offset, offset + len(unit), page))
            text += unit
            offset += len(unit)
        cursor = 0
        for piece in split_with_overlap(text, settings.chunk_size, settings.chunk_overlap):
            start = text.find(piece[:50], max(0, cursor - settings.chunk_overlap - 50))
            start = cursor if start < 0 else start
            end = start + len(piece)
            cursor = end
            pages = [p for s, e, p in spans if p is not None and s < end and e > start]
            chunks.append(
                Chunk(piece, section.heading_path, min(pages) if pages else None, max(pages) if pages else None)
            )
    return _number(chunks)


# --------------------------------------------------------------------------- semantic

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Ý0-9\"'«(\[])|\n+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(text) if s and s.strip()]


async def chunk_semantic(sections: list[Section], settings: ChunkingSettings, embed: EmbedFn) -> list[Chunk]:
    """Splits where the meaning shifts: cosine distance between neighbouring sentence windows
    above the configured percentile starts a new chunk. Section boundaries always split and
    chunk_size stays a hard ceiling (oversized pieces fall back to recursive splitting)."""
    chunks: list[Chunk] = []
    for section in sections:
        sentences: list[tuple[str, int | None]] = []
        for unit, page in section.units:
            if unit.startswith("|"):  # keep tables whole
                sentences.append((unit, page))
            else:
                sentences.extend((s, page) for s in split_sentences(unit))
        if not sentences:
            continue
        if len(sentences) < 3:
            groups = [sentences]
        else:
            vectors = np.array(await embed([s for s, _ in sentences]), dtype=np.float32)
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
            # Boundary before sentence i: compare the two sentences on its left with the two on
            # its right. Averaging smooths noise without blurring where the boundary falls.
            distances = np.empty(len(sentences) - 1, dtype=np.float32)
            for i in range(1, len(sentences)):
                left = vectors[max(0, i - 2) : i].mean(axis=0)
                right = vectors[i : i + 2].mean(axis=0)
                cos = float(left @ right) / ((np.linalg.norm(left) * np.linalg.norm(right)) or 1.0)
                distances[i - 1] = 1.0 - cos
            threshold = float(np.percentile(distances, settings.breakpoint_percentile))
            groups, current, length = [], [sentences[0]], len(sentences[0][0])
            for i, distance in enumerate(distances, start=1):
                sentence = sentences[i]
                too_long = length + len(sentence[0]) + 1 > settings.chunk_size
                if (distance > threshold and length >= settings.min_chunk_size) or too_long:
                    groups.append(current)
                    current, length = [], 0
                current.append(sentence)
                length += len(sentence[0]) + 1
            groups.append(current)

        for group in groups:
            text = " ".join(s for s, _ in group)
            first, last = _pages_of(group)
            pieces = [text] if len(text) <= settings.chunk_size else split_with_overlap(text, settings.chunk_size, settings.chunk_overlap)
            chunks.extend(Chunk(p, section.heading_path, first, last) for p in pieces)
    return _number(_merge_small(chunks, settings.min_chunk_size, settings.chunk_size))


def _merge_small(chunks: list[Chunk], min_size: int, max_size: int) -> list[Chunk]:
    merged: list[Chunk] = []
    for chunk in chunks:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and len(prev.text) < min_size
            and prev.heading_path == chunk.heading_path
            and len(prev.text) + len(chunk.text) + 1 <= max_size
        ):
            prev.text = f"{prev.text} {chunk.text}"
            prev.page_end = chunk.page_end or prev.page_end
        else:
            merged.append(chunk)
    return merged


def _number(chunks: list[Chunk]) -> list[Chunk]:
    for i, chunk in enumerate(chunks):
        chunk.index = i
    return chunks


async def chunk_document(blocks: list[Block], settings: ChunkingSettings, embed: EmbedFn) -> list[Chunk]:
    sections = build_sections(drop_running_headers(blocks))
    if settings.strategy == "semantic":
        return await chunk_semantic(sections, settings, embed)
    return chunk_recursive(sections, settings)


# --------------------------------------------------------------------------- language

STOPWORDS = {
    "it": {"il", "lo", "la", "gli", "le", "di", "che", "e", "è", "per", "non", "una", "del", "della", "con", "sono", "nel"},
    "en": {"the", "and", "of", "to", "is", "in", "that", "for", "it", "with", "as", "was", "on", "are", "this"},
    "de": {"der", "die", "und", "das", "ist", "nicht", "mit", "den", "ein", "zu", "von", "sich", "auf"},
    "fr": {"le", "la", "les", "et", "des", "est", "que", "une", "pour", "dans", "pas", "sur", "du", "au"},
    "es": {"el", "la", "los", "las", "y", "que", "es", "en", "por", "una", "con", "para", "del", "se"},
}


def detect_language(text: str) -> str | None:
    words = re.findall(r"[a-zà-ÿ]+", text[:20000].lower())
    if len(words) < 20:
        return None
    scores = {lang: sum(w in stop for w in words) for lang, stop in STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= len(words) * 0.05 else None
