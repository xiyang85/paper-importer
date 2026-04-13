"""
Fetch academic papers from arXiv using ar5iv.org (HTML version).
ar5iv converts LaTeX source to structured HTML, preserving sections,
figures, and math much better than PDF extraction.
"""

import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

AR5IV_BASE = "https://ar5iv.org/html"
ARXIV_PDF_BASE = "https://arxiv.org/pdf"
ARXIV_ABS_BASE = "https://arxiv.org/abs"

HEADERS = {
    "User-Agent": "paper-importer/0.1 (academic research tool)"
}


@dataclass
class Figure:
    label: str       # e.g. "Figure 1"
    caption: str
    image_url: str   # remote URL to download
    filename: str    # local filename to save as


@dataclass
class Section:
    title: str
    content: str     # plain text content of the section
    figures: list[Figure] = field(default_factory=list)


@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    year: str
    abstract: str
    sections: list[Section]
    pdf_url: str
    abs_url: str
    figures: list[Figure] = field(default_factory=list)  # all figures


def extract_arxiv_id(url_or_id: str) -> str:
    """Extract arXiv ID from a URL or bare ID string."""
    url_or_id = url_or_id.strip()

    # Bare ID like "1706.03762" or "2301.00001v2"
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", url_or_id):
        return url_or_id

    # Older format like "hep-th/9711200"
    if re.match(r"^[a-z-]+/\d{7}$", url_or_id):
        return url_or_id

    # URL formats: arxiv.org/abs/..., arxiv.org/pdf/..., ar5iv.org/html/...
    patterns = [
        r"arxiv\.org/(?:abs|pdf|html)/([^\s/?#]+)",
        r"ar5iv\.org/html/([^\s/?#]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1).rstrip("/")

    raise ValueError(f"Cannot extract arXiv ID from: {url_or_id}")


def fetch_paper(url_or_id: str) -> Paper:
    """Fetch a paper from ar5iv.org and return structured content."""
    arxiv_id = extract_arxiv_id(url_or_id)
    ar5iv_url = f"{AR5IV_BASE}/{arxiv_id}"

    response = requests.get(ar5iv_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    base_url = ar5iv_url

    title = _extract_title(soup)
    authors = _extract_authors(soup)
    year = _extract_year(soup)
    abstract = _extract_abstract(soup)
    sections, figures = _extract_sections(soup, base_url)

    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        sections=sections,
        figures=figures,
        pdf_url=f"{ARXIV_PDF_BASE}/{arxiv_id}",
        abs_url=f"{ARXIV_ABS_BASE}/{arxiv_id}",
    )


def _extract_title(soup: BeautifulSoup) -> str:
    for selector in [
        "h1.ltx_title",
        ".ltx_title_document",
        "title",
    ]:
        el = soup.select_one(selector)
        if el:
            return el.get_text(strip=True)
    return "Untitled"


def _extract_authors(soup: BeautifulSoup) -> list[str]:
    authors = []
    for el in soup.select(".ltx_personname"):
        # Remove footnote markers, superscripts, emails inside the element
        for junk in el.select("sup, .ltx_note, .ltx_contact"):
            junk.decompose()
        name = el.get_text(separator=" ", strip=True)
        # Drop anything that looks like an email, institution, or footnote blob
        if "@" in name:
            continue
        if len(name) > 60:
            continue
        # Keep only entries that look like a person name (at least two words,
        # starts with uppercase, no digits)
        if re.match(r"^[A-ZÁÉÍÓÚÀÈÙÂÊÎÔÛÄËÏÖÜÇŁŃŚŹ][a-záéíóúàèùâêîôûäëïöüçłńśź]+\s", name) and not re.search(r"\d", name):
            authors.append(name)
    return list(dict.fromkeys(authors)) or ["Unknown"]


def _extract_year(soup: BeautifulSoup) -> str:
    # Try date in metadata
    for el in soup.select(".ltx_dates, time"):
        text = el.get_text()
        m = re.search(r"\b(20\d{2}|19\d{2})\b", text)
        if m:
            return m.group(1)
    return ""


def _extract_abstract(soup: BeautifulSoup) -> str:
    el = soup.select_one(".ltx_abstract p, .ltx_abstract")
    if el:
        return _clean_text(el.get_text())
    return ""


def _extract_sections(
    soup: BeautifulSoup, base_url: str
) -> tuple[list[Section], list[Figure]]:
    body = soup.select_one(".ltx_document") or soup.body or soup

    # Select ALL section levels in document order:
    # ltx_section > ltx_subsection > ltx_subsubsection > ltx_paragraph
    all_sec_els = body.select(
        "section.ltx_section, section.ltx_subsection, "
        "section.ltx_subsubsection, section.ltx_paragraph, "
        "section.ltx_chapter, section.ltx_appendix"
    )

    if not all_sec_els:
        text = _clean_text(body.get_text())
        return [Section(title="Content", content=text)], []

    sections: list[Section] = []
    all_figures: list[Figure] = []
    fig_counter = [0]

    for sec_el in all_sec_els:
        title = _extract_section_title(sec_el)
        text_parts: list[str] = []
        figures: list[Figure] = []

        # Only process DIRECT children — child <section> elements are handled
        # as their own entries in the outer loop (no double-counting, no merge)
        for child in sec_el.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "section":
                continue
            _collect_content(child, text_parts, figures, fig_counter,
                             base_url, all_figures)

        content = "\n\n".join(text_parts)
        if content.strip() or figures:
            sections.append(Section(title=title, content=content, figures=figures))

    return sections, all_figures


def _collect_content(
    el: Tag,
    text_parts: list[str],
    figures: list[Figure],
    fig_counter: list[int],
    base_url: str,
    all_figures: list[Figure],
) -> None:
    """Recursively collect text and figures from an element.
    Does NOT cross <section> boundaries."""
    if not isinstance(el, Tag):
        return

    # Never recurse into nested sections
    if el.name == "section":
        return

    classes: list[str] = el.get("class") or []

    # Paragraph — the main content unit in ar5iv
    if el.name == "p" and "ltx_p" in classes:
        text = _clean_text(el.get_text())
        if text:
            text_parts.append(text)
        return

    # Figure
    if el.name == "figure" and "ltx_figure" in classes:
        fig = _extract_figure(el, base_url, fig_counter)
        if fig:
            figures.append(fig)
            all_figures.append(fig)
        return

    # Skip equation tables (inline math rendered as tables by ar5iv)
    if el.name == "table" and any("ltx_eqn" in c for c in classes):
        return

    # Data table — extract as plain text
    if el.name == "table":
        text = _clean_text(el.get_text())
        if text and len(text) > 10:
            text_parts.append(text)
        return

    # Recurse into everything else (div.ltx_para, div.ltx_noindent, etc.)
    for child in el.children:
        if isinstance(child, Tag):
            _collect_content(child, text_parts, figures, fig_counter,
                             base_url, all_figures)


def _extract_section_title(sec_el: Tag) -> str:
    heading = sec_el.find(re.compile(r"^h\d$"))
    if heading:
        return _clean_text(heading.get_text())
    title_el = sec_el.select_one(".ltx_title")
    if title_el:
        return _clean_text(title_el.get_text())
    return "Section"


def _extract_figure(
    fig_el: Tag, base_url: str, counter: list[int]
) -> Figure | None:
    img = fig_el.find("img")
    if not img:
        return None

    img_src = img.get("src", "")
    if not img_src:
        return None

    # Resolve relative URLs
    image_url = urllib.parse.urljoin(base_url, img_src)

    caption_el = fig_el.select_one(".ltx_caption, figcaption")
    caption = _clean_text(caption_el.get_text()) if caption_el else ""

    # Try to get figure number from caption or id
    label = ""
    m = re.search(r"Figure\s+(\w+)", caption, re.IGNORECASE)
    if m:
        label = f"Figure {m.group(1)}"
    else:
        counter[0] += 1
        label = f"Figure {counter[0]}"

    filename = f"fig{counter[0]}.png"

    return Figure(
        label=label,
        caption=caption,
        image_url=image_url,
        filename=filename,
    )


def _clean_text(text: str) -> str:
    """Clean extracted text: collapse whitespace, strip artifacts."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def download_pdf(arxiv_id: str, dest: Path) -> None:
    """Download the original PDF from arXiv."""
    url = f"{ARXIV_PDF_BASE}/{arxiv_id}"
    response = requests.get(url, headers=HEADERS, stream=True, timeout=60)
    response.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def download_figure(figure: Figure, dest: Path) -> bool:
    """Download a figure image. Returns True on success."""
    try:
        response = requests.get(
            figure.image_url, headers=HEADERS, stream=True, timeout=30
        )
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception:
        return False
