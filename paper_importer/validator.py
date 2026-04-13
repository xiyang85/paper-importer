"""
Automatic validation across all stages of paper import.

Two severity levels:
  WARN  — suspicious but non-fatal; import continues, user is notified
  ERROR — critical failure; import should abort

Usage:
    from .validator import Validator
    v = Validator()
    v.check_extraction(paper)
    v.check_translation(sections_en, sections_zh, abstract_en, abstract_zh)
    v.check_downloads(paper_dir, paper)
    v.check_markdown(paper_dir, markdown)
    v.report()           # prints summary
    v.has_errors()       # True if any ERROR-level issue found
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Issue:
    level: str   # "WARN" or "ERROR"
    stage: str
    message: str


class Validator:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    # ------------------------------------------------------------------
    # Stage 1: Extraction
    # ------------------------------------------------------------------

    def check_extraction(self, paper) -> None:
        """Validate content extracted from ar5iv / generic fetcher."""
        stage = "extraction"

        # ar5iv may redirect old/missing papers to a stub page
        if not paper.title or paper.title in ("Untitled", ""):
            self._error(stage, "No title extracted — paper may not exist on ar5iv")

        if not paper.sections:
            self._error(stage, "No sections extracted — HTML structure may have changed")
            return

        total_words = sum(len(s.content.split()) for s in paper.sections)
        if total_words < 300:
            self._warn(
                stage,
                f"Very little text extracted ({total_words} words total). "
                "Paper may be image-only or ar5iv conversion failed."
            )

        if not getattr(paper, "abstract", ""):
            self._warn(stage, "Abstract not found — check if paper has an abstract section")

        # Detect likely ar5iv error page (returns HTML with title like "ar5iv")
        if paper.title.lower().startswith("ar5iv") or paper.title.lower() == "404":
            self._error(stage, f"ar5iv may have returned an error page (title: '{paper.title}')")

        # Check for sections with no content at all (excluding figure-only sections)
        empty_sections = [
            s.title for s in paper.sections
            if not s.content.strip() and not s.figures
        ]
        if empty_sections:
            self._warn(
                stage,
                f"{len(empty_sections)} empty section(s): "
                + ", ".join(f'"{t}"' for t in empty_sections[:5])
            )

        # Figure filename uniqueness
        figures = getattr(paper, "figures", [])
        filenames = [f.filename for f in figures]
        if len(filenames) != len(set(filenames)):
            from collections import Counter
            dupes = [fn for fn, n in Counter(filenames).items() if n > 1]
            self._error(
                stage,
                f"Duplicate figure filenames detected: {dupes}. "
                "Only the last downloaded file will survive."
            )

    # ------------------------------------------------------------------
    # Stage 2: Translation
    # ------------------------------------------------------------------

    def check_translation(
        self,
        sections_en: list[dict],
        sections_zh: list[str],
        abstract_en: str,
        abstract_zh: str,
    ) -> None:
        stage = "translation"

        if len(sections_en) != len(sections_zh):
            self._error(
                stage,
                f"Section count mismatch: {len(sections_en)} EN vs "
                f"{len(sections_zh)} ZH sections"
            )

        for i, (sec_en, zh) in enumerate(zip(sections_en, sections_zh)):
            en_text = sec_en.get("content", "")
            title = sec_en.get("title", f"section {i+1}")

            if en_text.strip() and not zh.strip():
                self._error(stage, f'Section "{title}": translation is empty')
                continue

            # Check for un-restored placeholders
            if "PAPER_IMPORTER_TABLE_" in zh:
                self._error(
                    stage,
                    f'Section "{title}": table placeholder not restored in translation'
                )

            # Length ratio check (exclude table-heavy sections)
            en_words = len(en_text.split())
            zh_chars = len(zh.replace(" ", ""))
            if en_words > 30 and zh_chars < en_words * 0.6:
                self._warn(
                    stage,
                    f'Section "{title}": translation seems short '
                    f"({zh_chars} zh-chars vs {en_words} en-words). "
                    "Possible truncation."
                )

            # Check output is actually Chinese
            if zh.strip() and en_words > 20:
                cjk_count = sum(1 for c in zh if "\u4e00" <= c <= "\u9fff")
                if cjk_count < 5:
                    self._warn(
                        stage,
                        f'Section "{title}": output contains very few Chinese characters '
                        f"({cjk_count}). API may have returned non-Chinese text."
                    )

        # Abstract checks
        if abstract_en.strip() and not abstract_zh.strip():
            self._error(stage, "Abstract translation is empty")
        if abstract_zh and "PAPER_IMPORTER_TABLE_" in abstract_zh:
            self._error(stage, "Abstract: table placeholder not restored")

    # ------------------------------------------------------------------
    # Stage 3: Downloads
    # ------------------------------------------------------------------

    def check_downloads(self, paper_dir: Path, paper) -> None:
        stage = "download"

        # Figure files
        figures = getattr(paper, "figures", [])
        for fig in figures:
            fig_path = paper_dir / "figures" / fig.filename
            if not fig_path.exists():
                self._warn(stage, f"{fig.filename}: file not found after download")
            elif fig_path.stat().st_size < 500:
                self._warn(
                    stage,
                    f"{fig.filename}: file is suspiciously small "
                    f"({fig_path.stat().st_size} bytes) — may be an error page"
                )

        # PDF file
        pdf_path = paper_dir / "paper.pdf"
        if pdf_path.exists():
            pdf_size = pdf_path.stat().st_size
            if pdf_size < 10_000:
                self._warn(
                    stage,
                    f"paper.pdf is very small ({pdf_size} bytes) — "
                    "download may have failed or returned an error page"
                )

    # ------------------------------------------------------------------
    # Stage 4: Generated markdown
    # ------------------------------------------------------------------

    def check_markdown(self, paper_dir: Path, markdown: str) -> None:
        stage = "markdown"

        # Check referenced figure files exist
        refs = re.findall(r"!\[.*?\]\((figures/[^)]+)\)", markdown)
        for ref in refs:
            fig_file = paper_dir / ref
            if not fig_file.exists():
                self._warn(stage, f"Markdown references '{ref}' but file does not exist")

        # Check for raw placeholder remnants
        if "PAPER_IMPORTER_TABLE_" in markdown:
            self._error(stage, "Un-restored table placeholder found in final markdown")

        # Check frontmatter closed properly
        fm_closes = [i for i, l in enumerate(markdown.splitlines()) if l == "---"]
        if len(fm_closes) < 2:
            self._warn(stage, "Frontmatter may be malformed (fewer than 2 '---' delimiters)")

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self) -> None:
        """Print all issues to stdout."""
        if not self.issues:
            print("  ✓ All checks passed")
            return
        for issue in self.issues:
            icon = "✗" if issue.level == "ERROR" else "⚠"
            print(f"  {icon} [{issue.stage}] {issue.message}")

    def has_errors(self) -> bool:
        return any(i.level == "ERROR" for i in self.issues)

    def warn_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "WARN")

    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "ERROR")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _warn(self, stage: str, message: str) -> None:
        self.issues.append(Issue("WARN", stage, message))

    def _error(self, stage: str, message: str) -> None:
        self.issues.append(Issue("ERROR", stage, message))
