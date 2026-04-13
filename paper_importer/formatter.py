"""
Generate Obsidian-compatible markdown with interleaved Chinese/English content.
Frontmatter is designed to be fully Dataview-queryable.
"""

import re
from datetime import date
from pathlib import Path


def _is_table_block(para: str) -> bool:
    """Return True if this paragraph is a Markdown table (has a separator row)."""
    return bool(re.search(r"^\| ?[-:]+", para, re.MULTILINE))


def slugify(text: str) -> str:
    """Convert title to a safe directory/file name."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


def make_paper_dir_name(arxiv_id: str, title: str) -> str:
    return f"{arxiv_id}-{slugify(title)}"


def make_web_dir_name(title: str) -> str:
    return slugify(title)


def _truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def generate_markdown(
    title: str,
    authors: list[str],
    year: str,
    abstract_en: str,
    abstract_zh: str,
    sections_en: list[dict],
    sections_zh: list[str],
    source_url: str,
    abs_url: str,
    figures_by_section: list[list] | None = None,
    tags: list[str] | None = None,
    has_pdf: bool = False,
    arxiv_id: str = "",
    content_type: str = "paper",  # "paper" | "article"
) -> str:
    today = date.today().isoformat()
    tags_yaml = tags or [content_type]

    lines = []

    # --- YAML frontmatter (Dataview-compatible) ---
    lines.append("---")
    lines.append(f'title: "{_escape_yaml(title)}"')

    # Authors as YAML list for Dataview filtering
    if len(authors) == 1:
        lines.append(f'authors: "{_escape_yaml(authors[0])}"')
    else:
        lines.append("authors:")
        for a in authors:
            lines.append(f'  - "{_escape_yaml(a)}"')

    if year:
        lines.append(f"year: {year}")
    lines.append(f"imported: {today}")
    lines.append(f'source: "{source_url}"')
    if abs_url and abs_url != source_url:
        lines.append(f'arxiv_abs: "{abs_url}"')
    if arxiv_id:
        lines.append(f'arxiv_id: "{arxiv_id}"')
    lines.append(f"type: {content_type}")

    # Tags as YAML list
    lines.append("tags:")
    for tag in tags_yaml:
        lines.append(f"  - {tag}")

    if has_pdf:
        lines.append("pdf: paper.pdf")

    # Short Chinese abstract for Dataview search/display
    if abstract_zh:
        short_zh = _truncate(abstract_zh, 300)
        lines.append(f'abstract_zh: "{_escape_yaml(short_zh)}"')

    lines.append("---")
    lines.append("")

    # --- Title & metadata block ---
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**作者:** {', '.join(authors)}")
    if year:
        lines.append(f"**年份:** {year}")
    lines.append(f"**来源:** [{source_url}]({source_url})")
    if abs_url and abs_url != source_url:
        lines.append(f"**摘要页:** [{abs_url}]({abs_url})")
    if has_pdf:
        lines.append("**PDF:** [[paper.pdf]]")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- Abstract ---
    if abstract_en or abstract_zh:
        lines.append("## Abstract")
        lines.append("")
        if abstract_zh:
            lines.append(f"> **【中文】** {abstract_zh}")
            lines.append("")
        if abstract_en:
            lines.append(f"> **【English】** {abstract_en}")
            lines.append("")
        lines.append("---")
        lines.append("")

    # --- Sections ---
    for i, (sec_en, zh_text) in enumerate(zip(sections_en, sections_zh)):
        sec_title = sec_en.get("title", "")
        en_text = sec_en.get("content", "").strip()
        zh_text = zh_text.strip() if zh_text else ""

        if not en_text and not zh_text:
            continue

        lines.append(f"## {sec_title}")
        lines.append("")

        en_paragraphs = [p.strip() for p in en_text.split("\n\n") if p.strip()]
        zh_paragraphs = [p.strip() for p in zh_text.split("\n\n") if p.strip()]

        max_len = max(len(en_paragraphs), len(zh_paragraphs))
        for j in range(max_len):
            zh_para = zh_paragraphs[j] if j < len(zh_paragraphs) else ""
            en_para = en_paragraphs[j] if j < len(en_paragraphs) else ""

            # Tables: render once as-is, no 【中文】/【English】 prefix
            if _is_table_block(en_para):
                lines.append(en_para)
                lines.append("")
            else:
                if zh_para:
                    lines.append(f"**【中文】** {zh_para}")
                    lines.append("")
                if en_para:
                    lines.append(f"**【English】** {en_para}")
                    lines.append("")

        # Figures for this section
        if figures_by_section and i < len(figures_by_section):
            for fig in figures_by_section[i]:
                lines.append(
                    f"![{fig.label}: {fig.caption}](figures/{fig.filename})"
                )
                lines.append("")
                if fig.caption:
                    lines.append(f"*{fig.caption}*")
                    lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def generate_index_page(papers_folder: str) -> str:
    """Generate an Obsidian Dataview index note for the papers folder."""
    today = date.today().isoformat()
    return f"""---
created: {today}
---

# Papers Index

> 自动生成的论文索引页。需要安装 [Dataview](https://github.com/blacksmithgu/obsidian-dataview) 插件。

## 所有论文

```dataview
TABLE
  authors AS "作者",
  year AS "年份",
  abstract_zh AS "摘要（中）",
  source AS "来源"
FROM "{papers_folder}"
WHERE type = "paper"
SORT year DESC, file.mtime DESC
```

## 按年份分组

```dataview
TABLE WITHOUT ID
  "[[" + file.path + "|" + title + "]]" AS "论文",
  authors AS "作者",
  abstract_zh AS "摘要（中）"
FROM "{papers_folder}"
WHERE type = "paper"
GROUP BY year
SORT year DESC
```

## 最近导入

```dataview
TABLE
  title AS "标题",
  year AS "年份",
  imported AS "导入日期"
FROM "{papers_folder}"
WHERE type = "paper"
SORT imported DESC
LIMIT 10
```

## 文章 / 博客

```dataview
TABLE
  authors AS "作者",
  imported AS "导入日期",
  source AS "来源"
FROM "{papers_folder}"
WHERE type = "article"
SORT imported DESC
```
"""


def write_paper_to_vault(
    vault_path: Path,
    papers_folder: str,
    dir_name: str,
    markdown: str,
) -> Path:
    paper_dir = vault_path / papers_folder / dir_name
    paper_dir.mkdir(parents=True, exist_ok=True)
    md_path = paper_dir / "index.md"
    md_path.write_text(markdown, encoding="utf-8")
    (paper_dir / "figures").mkdir(exist_ok=True)
    return md_path


def write_index_to_vault(vault_path: Path, papers_folder: str) -> Path:
    index_dir = vault_path / papers_folder
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / "_index.md"
    index_path.write_text(generate_index_page(papers_folder), encoding="utf-8")
    return index_path


def _escape_yaml(text: str) -> str:
    return text.replace('"', '\\"').replace("\n", " ")
