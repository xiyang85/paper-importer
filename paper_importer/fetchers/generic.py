"""
Generic URL fetcher for blogs, journals, and other web pages.
Uses trafilatura for main-content extraction.
"""

from dataclasses import dataclass, field

import requests
import trafilatura


HEADERS = {
    "User-Agent": "paper-importer/0.1 (academic research tool)"
}


@dataclass
class Section:
    title: str
    content: str
    figures: list = field(default_factory=list)


@dataclass
class WebContent:
    url: str
    title: str
    authors: list[str]
    date: str
    sections: list[Section]
    figures: list = field(default_factory=list)
    pdf_url: str = ""
    abs_url: str = ""


def fetch_url(url: str) -> WebContent:
    """Fetch and extract main content from any URL."""
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    html = response.text

    # trafilatura: extracts main content, removes nav/footer/ads
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
    )

    # Also get metadata
    meta = trafilatura.extract_metadata(html)

    title = (meta.title if meta and meta.title else "") or _extract_title_fallback(html)
    authors = []
    if meta and meta.author:
        authors = [a.strip() for a in meta.author.split(",") if a.strip()]
    date = (meta.date if meta and meta.date else "") or ""

    if not text:
        raise ValueError(f"Could not extract content from: {url}")

    # Split into sections by headers (lines starting with #) or paragraphs
    sections = _split_into_sections(text)

    return WebContent(
        url=url,
        title=title or "Untitled",
        authors=authors or ["Unknown"],
        date=date,
        sections=sections,
    )


def _extract_title_fallback(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    if soup.title:
        return soup.title.get_text(strip=True)
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _split_into_sections(text: str) -> list[Section]:
    """Split extracted text into sections based on markdown headers or paragraphs."""
    lines = text.split("\n")
    sections = []
    current_title = "Content"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Detect markdown-style headers
        if stripped.startswith("#"):
            if current_lines:
                content = "\n\n".join(
                    p.strip() for p in
                    "\n".join(current_lines).split("\n\n")
                    if p.strip()
                )
                if content:
                    sections.append(Section(title=current_title, content=content))
            current_title = stripped.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Flush remaining content
    if current_lines:
        content = "\n\n".join(
            p.strip() for p in
            "\n".join(current_lines).split("\n\n")
            if p.strip()
        )
        if content:
            sections.append(Section(title=current_title, content=content))

    return sections or [Section(title="Content", content=text)]
