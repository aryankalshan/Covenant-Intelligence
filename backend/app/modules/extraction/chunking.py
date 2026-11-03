from dataclasses import dataclass

from app.modules.agreements.models import DocumentPage


@dataclass(frozen=True)
class PageExcerpt:
    page_number: int
    text: str


@dataclass(frozen=True)
class DocumentChunk:
    index: int
    excerpts: tuple[PageExcerpt, ...]
    text: str

    @property
    def page_numbers(self) -> list[int]:
        return sorted({excerpt.page_number for excerpt in self.excerpts})


def _page_windows(page_number: int, text: str, max_chars: int, overlap_chars: int) -> list[PageExcerpt]:
    if len(text) <= max_chars:
        return [PageExcerpt(page_number, text)]
    windows: list[PageExcerpt] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            paragraph = text.rfind("\n\n", start + max_chars // 2, end)
            if paragraph > start:
                end = paragraph
        if end <= start:
            end = min(start + max_chars, len(text))
        windows.append(PageExcerpt(page_number, text[start:end]))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap_chars)
    return windows


def build_chunks(pages: list[DocumentPage], *, max_chars: int = 12_000, overlap_chars: int = 1_000) -> list[DocumentChunk]:
    """Build bounded chunks with explicit 1-based page markers and per-page overlap."""
    if max_chars < 500 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("Chunk size must be >= 500 and overlap must be smaller than chunk size.")
    # Reserve room for page markers and separators so the serialized prompt text
    # never exceeds the configured bound, even for a page per chunk.
    text_budget = max_chars - 80
    windows = [
        excerpt
        for page in sorted(pages, key=lambda item: item.page_number)
        if page.text and page.text.strip()
        for excerpt in _page_windows(page.page_number, page.text, text_budget, min(overlap_chars, text_budget - 1))
    ]
    chunks: list[DocumentChunk] = []
    current: list[PageExcerpt] = []
    current_size = 0
    for excerpt in windows:
        marker_size = len(f"\n[SOURCE PAGE {excerpt.page_number}]\n")
        separator_size = 2 if current else 0
        projected = current_size + separator_size + marker_size + len(excerpt.text)
        if current and projected > max_chars:
            chunks.append(_make_chunk(len(chunks) + 1, current))
            current, current_size = [], 0
        current.append(excerpt)
        current_size += separator_size + marker_size + len(excerpt.text)
    if current:
        chunks.append(_make_chunk(len(chunks) + 1, current))
    return chunks


def _make_chunk(index: int, excerpts: list[PageExcerpt]) -> DocumentChunk:
    parts = [f"[SOURCE PAGE {excerpt.page_number}]\n{excerpt.text}" for excerpt in excerpts]
    return DocumentChunk(index=index, excerpts=tuple(excerpts), text="\n\n".join(parts))


def relevant_chunks(chunks: list[DocumentChunk], categories: list[str]) -> list[DocumentChunk]:
    """Return the full document for extraction; lexical filtering caused false negatives.

    `categories` still scopes the model's task through the prompt, but must not be
    used to drop source text: covenant language and definitions vary too widely
    for a keyword list to prove that a chunk is irrelevant. Large documents are
    bounded by the explicit max-chunk limit in the extraction service, which
    reports any resulting incomplete coverage.
    """
    del categories
    return list(chunks)
