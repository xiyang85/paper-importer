"""
Local PDF fetcher using PyMuPDF (fitz).

Extracts structured text from academic PDFs by analyzing font sizes:
- Large / bold text → section heading
- "Abstract" keyword → abstract block
- Modal font size → body text
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mode


@dataclass
class Section:
    title: str
    content: str
    figures: list = field(default_factory=list)


@dataclass
class PDFContent:
    title: str
    authors: list[str]
    year: str
    abstract: str
    sections: list[Section]
    figures: list = field(default_factory=list)
    pdf_url: str = ""
    abs_url: str = ""


def fetch_pdf(path: Path) -> PDFContent:
    """Extract structured content from a local PDF file."""
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError(
            "PyMuPDF is required for PDF import. "
            "Install it with: uv pip install pymupdf"
        )

    doc = fitz.open(str(path))
    blocks = _extract_blocks(doc)
    doc.close()

    body_size = _detect_body_font_size(blocks)
    title = _extract_title(blocks, body_size)
    authors = _extract_authors(blocks, body_size)
    year = _extract_year(blocks)
    abstract = _extract_abstract(blocks)
    sections = _extract_sections(blocks, body_size, abstract)

    return PDFContent(
        title=title or path.stem,
        authors=authors or ["Unknown"],
        year=year,
        abstract=abstract,
        sections=sections,
        pdf_url=str(path),
        abs_url="",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    text: str
    size: float
    bold: bool
    page: int


def _extract_blocks(doc) -> list[_Block]:
    """Extract all text spans from the document with font metadata."""
    blocks: list[_Block] = []
    for page_num, page in enumerate(doc):
        data = page.get_text("dict", flags=11)  # preserve whitespace
        for block in data.get("blocks", []):
            if block.get("type") != 0:  # skip image blocks
                continue
            for line in block.get("lines", []):
                line_text = ""
                max_size = 0.0
                is_bold = False
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                    size = span.get("size", 0)
                    if size > max_size:
                        max_size = size
                    flags = span.get("flags", 0)
                    if flags & 2**4:  # bold flag
                        is_bold = True
                text = line_text.strip()
                if text:
                    blocks.append(_Block(
                        text=text,
                        size=round(max_size, 1),
                        bold=is_bold,
                        page=page_num,
                    ))
    return blocks


def _detect_body_font_size(blocks: list[_Block]) -> float:
    """The modal font size is the body text size."""
    sizes = [b.size for b in blocks if b.size > 0]
    if not sizes:
        return 10.0
    try:
        return mode(sizes)
    except Exception:
        return sorted(sizes)[len(sizes) // 2]


def _is_heading(block: _Block, body_size: float) -> bool:
    """Heuristic: a block is a heading if it's larger or bold and short."""
    if len(block.text) > 150:
        return False
    is_larger = block.size >= body_size * 1.15
    is_bold_short = block.bold and len(block.text) < 80
    # Numbered section patterns: "1.", "1.1", "2 Introduction"
    is_numbered = bool(re.match(r"^\d+(\.\d+)*\.?\s+\w", block.text))
    return (is_larger or is_bold_short or is_numbered) and block.page < 30


def _extract_title(blocks: list[_Block], body_size: float) -> str:
    """Title is typically the largest text on the first page."""
    first_page = [b for b in blocks if b.page == 0]
    if not first_page:
        return ""
    # Sort by font size descending, pick the largest block on page 1
    candidates = sorted(first_page, key=lambda b: -b.size)
    for b in candidates:
        if len(b.text) > 10 and not re.match(r"^\d", b.text):
            return b.text
    return candidates[0].text if candidates else ""


def _extract_authors(blocks: list[_Block], body_size: float) -> list[str]:
    """
    Authors usually appear on the first 2 pages between the title and abstract.
    Heuristic: look for comma/and-separated names after the title block.
    """
    first_pages = [b for b in blocks if b.page <= 1]
    abstract_idx = next(
        (i for i, b in enumerate(first_pages)
         if re.search(r"\babstract\b", b.text, re.IGNORECASE)),
        len(first_pages),
    )
    # Take blocks between title and abstract
    candidates = first_pages[1:abstract_idx]

    # Rough author detection: blocks that have commas, "and", "@" (email lines excluded)
    authors = []
    for b in candidates:
        text = b.text.strip()
        if "@" in text or "University" in text or "Institute" in text:
            continue
        if len(text) < 5 or len(text) > 200:
            continue
        if re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", text):
            # Split on commas and "and"
            parts = re.split(r",\s*|\s+and\s+", text)
            for p in parts:
                p = p.strip()
                if re.match(r"[A-Z][a-z]+ [A-Z]", p):
                    authors.append(p)
    return list(dict.fromkeys(authors))  # deduplicate preserving order


def _extract_year(blocks: list[_Block]) -> str:
    """Find a 4-digit year in the first few pages."""
    for b in [b for b in blocks if b.page <= 2]:
        m = re.search(r"\b(20\d{2}|19\d{2})\b", b.text)
        if m:
            return m.group(1)
    return ""


def _extract_abstract(blocks: list[_Block]) -> str:
    """Extract the abstract section."""
    abstract_lines = []
    in_abstract = False
    for b in blocks:
        if re.match(r"^abstract\s*$", b.text, re.IGNORECASE):
            in_abstract = True
            continue
        if in_abstract:
            # Stop at next section heading or keyword
            if re.match(
                r"^\d+\.?\s+\w|^introduction$|^keywords?\s*:|^1\s+intro",
                b.text, re.IGNORECASE
            ):
                break
            abstract_lines.append(b.text)
    return " ".join(abstract_lines).strip()


def _extract_sections(
    blocks: list[_Block], body_size: float, abstract: str
) -> list[Section]:
    """Split the document into sections using heading detection."""
    sections: list[Section] = []
    current_title = "Content"
    current_lines: list[str] = []
    past_abstract = not abstract  # skip to content if no abstract found

    for b in blocks:
        # Skip until we're past the abstract area
        if not past_abstract:
            if re.match(r"^\d+\.?\s+\w|^introduction", b.text, re.IGNORECASE):
                past_abstract = True
            else:
                continue

        if _is_heading(b, body_size):
            # Flush current section
            content = _join_lines(current_lines)
            if content:
                sections.append(Section(title=current_title, content=content))
            current_title = b.text
            current_lines = []
        else:
            current_lines.append(b.text)

    # Flush last section
    content = _join_lines(current_lines)
    if content:
        sections.append(Section(title=current_title, content=content))

    # Filter out very short junk sections (page numbers, etc.)
    sections = [s for s in sections if len(s.content) > 50]

    # If no sections detected, return entire text as one section
    if not sections:
        all_text = _join_lines([b.text for b in blocks])
        return [Section(title="Content", content=all_text)]

    return sections


def _join_lines(lines: list[str]) -> str:
    """Join extracted lines into paragraphs, merging hyphenated line breaks."""
    text = ""
    for line in lines:
        if text.endswith("-"):
            text = text[:-1] + line  # merge hyphenated words
        elif text and not text.endswith(" "):
            text += " " + line
        else:
            text += line
    return text.strip()
