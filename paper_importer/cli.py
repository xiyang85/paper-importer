"""
CLI entry point for paper-importer.

Commands:
  paper setup         - configure vault path and API key
  paper add <url>     - import a paper from arXiv, any URL, or local PDF
  paper batch <file>  - import multiple papers from a list file
  paper index         - generate/update the Dataview index page
  paper config        - show current configuration
"""

import re
import sys
from pathlib import Path

import click

from . import config as cfg
from . import cache as translation_cache
from .fetchers import arxiv as arxiv_fetcher
from .fetchers import generic as generic_fetcher
from .fetchers import pdf as pdf_fetcher
from . import translator as trans
from . import formatter as fmt
from .validator import Validator


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def _is_arxiv(url: str) -> bool:
    url = url.strip()
    return (
        "arxiv.org" in url
        or "ar5iv.org" in url
        or bool(re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", url))
        or bool(re.match(r"^[a-z-]+/\d{7}$", url))
    )


def _is_local_pdf(path_str: str) -> bool:
    p = Path(path_str).expanduser()
    return p.suffix.lower() == ".pdf" and p.exists()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Import academic papers into Obsidian with Chinese translation."""
    pass


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@cli.command()
def setup():
    """Configure vault path and Anthropic API key."""
    click.echo("=== paper-importer setup ===\n")
    current = cfg.get_config()

    vault = click.prompt(
        "Obsidian vault path",
        default=current.get("vault_path", ""),
    )
    vault_path = Path(vault).expanduser().resolve()
    if not vault_path.exists():
        click.confirm(f"Path {vault_path} does not exist. Create it?", abort=True)
        vault_path.mkdir(parents=True)

    api_key = click.prompt(
        "Anthropic API key",
        default=current.get("api_key", ""),
        hide_input=True,
    )

    papers_folder = click.prompt(
        "Papers subfolder in vault",
        default=current.get("papers_folder", "Papers"),
    )

    cfg.save_config({
        "vault_path": str(vault_path),
        "api_key": api_key,
        "papers_folder": papers_folder,
    })
    click.echo(f"\nSaved to {cfg.CONFIG_FILE}")
    click.echo(f"Papers → {vault_path}/{papers_folder}/")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@cli.command()
def config():
    """Show current configuration."""
    current = cfg.get_config()
    if not current:
        click.echo("Not configured yet. Run `paper setup` first.")
        return
    click.echo(f"Vault path:    {current.get('vault_path', 'not set')}")
    click.echo(f"Papers folder: {current.get('papers_folder', 'Papers')}")
    key = current.get("api_key", "")
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "not set"
    click.echo(f"API key:       {masked}")
    click.echo(f"Config file:   {cfg.CONFIG_FILE}")


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("source")
@click.option("--no-pdf", is_flag=True, help="Skip downloading the PDF (arXiv only)")
@click.option("--no-figures", is_flag=True, help="Skip downloading figures (arXiv only)")
@click.option("--model", default="claude-opus-4-6", show_default=True,
              help="Claude model for translation")
@click.option("--tags", default="", help="Comma-separated extra tags")
def add(source: str, no_pdf: bool, no_figures: bool, model: str, tags: str):
    """Import a paper from arXiv URL/ID, any website URL, or a local PDF file."""
    try:
        vault_path = cfg.get_vault_path()
        api_key = cfg.get_api_key()
        papers_folder = cfg.get_papers_folder()
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    extra_tags = [t.strip() for t in tags.split(",") if t.strip()]

    if _is_local_pdf(source):
        _import_pdf(source, vault_path, papers_folder, api_key, model, extra_tags)
    elif _is_arxiv(source):
        _import_arxiv(source, vault_path, papers_folder, api_key, model,
                      no_pdf, no_figures, extra_tags)
    else:
        _import_generic(source, vault_path, papers_folder, api_key, model, extra_tags)


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--no-pdf", is_flag=True)
@click.option("--no-figures", is_flag=True)
@click.option("--model", default="claude-opus-4-6", show_default=True)
@click.option("--tags", default="")
def batch(file: str, no_pdf: bool, no_figures: bool, model: str, tags: str):
    """Import multiple papers from a list file (one URL/ID/path per line).

    Lines starting with # are treated as comments and skipped.
    Blank lines are skipped.

    Example file:

    \b
      # Transformer paper
      https://arxiv.org/abs/1706.03762
      1810.04805
      /path/to/local.pdf
      https://lilianweng.github.io/posts/2023-06-23-agent/
    """
    lines = Path(file).read_text(encoding="utf-8").splitlines()
    sources = [
        l.strip() for l in lines
        if l.strip() and not l.strip().startswith("#")
    ]

    if not sources:
        click.echo("No entries found in file.")
        return

    click.echo(f"Found {len(sources)} entries to import.\n")

    ok = 0
    failed: list[tuple[str, str]] = []

    for i, source in enumerate(sources, 1):
        click.echo(f"[{i}/{len(sources)}] {source}")
        try:
            ctx = click.get_current_context()
            ctx.invoke(
                add,
                source=source,
                no_pdf=no_pdf,
                no_figures=no_figures,
                model=model,
                tags=tags,
            )
            ok += 1
        except SystemExit:
            failed.append((source, "import error"))
        except Exception as e:
            click.echo(f"  ✗ Failed: {e}", err=True)
            failed.append((source, str(e)))
        click.echo("")

    click.echo(f"Batch complete: {ok}/{len(sources)} succeeded.")
    if failed:
        click.echo("\nFailed entries:")
        for src, reason in failed:
            click.echo(f"  {src} — {reason}")


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------

@cli.command()
def index():
    """Create or update the Dataview index page in your papers folder.

    Requires the Obsidian Dataview plugin to render the queries.
    Install it from: https://github.com/blacksmithgu/obsidian-dataview
    """
    try:
        vault_path = cfg.get_vault_path()
        papers_folder = cfg.get_papers_folder()
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    index_path = fmt.write_index_to_vault(vault_path, papers_folder)
    click.echo(f"Index page written: {index_path}")
    click.echo(f"Open in Obsidian: {papers_folder}/_index.md")
    click.echo("\nNote: install the Dataview plugin in Obsidian to render queries.")


# ---------------------------------------------------------------------------
# Import implementations
# ---------------------------------------------------------------------------

def _import_arxiv(
    url: str,
    vault_path: Path,
    papers_folder: str,
    api_key: str,
    model: str,
    no_pdf: bool,
    no_figures: bool,
    extra_tags: list[str],
) -> None:
    v = Validator()

    click.echo(f"Fetching from ar5iv: {url}")
    try:
        paper = arxiv_fetcher.fetch_paper(url)
    except Exception as e:
        click.echo(f"Error fetching paper: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Title:    {paper.title}")
    click.echo(f"  Authors:  {', '.join(paper.authors[:3])}{'...' if len(paper.authors) > 3 else ''}")
    click.echo(f"  Sections: {len(paper.sections)}  Figures: {len(paper.figures)}")

    # --- Stage 1: validate extraction ---
    v.check_extraction(paper)
    _print_issues(v, "extraction")
    if v.has_errors():
        sys.exit(1)

    # --- Stage 2: translate ---
    click.echo("\nTranslating abstract...")
    abstract_zh, abs_cached = trans.translate_abstract(paper.abstract, api_key, model)
    if abs_cached:
        click.echo("  (cached)")

    sections_data = [{"title": s.title, "content": s.content} for s in paper.sections]
    sections_zh, hits, calls = _translate_with_progress(sections_data, api_key, model)
    _print_cache_stats(hits, calls)

    v.check_translation(sections_data, sections_zh, paper.abstract, abstract_zh)
    _print_issues(v, "translation")
    if v.has_errors():
        sys.exit(1)

    # --- Stage 3: generate markdown ---
    figures_by_section = [s.figures for s in paper.sections]
    tags = ["paper", "arxiv"] + extra_tags

    markdown = fmt.generate_markdown(
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        abstract_en=paper.abstract,
        abstract_zh=abstract_zh,
        sections_en=sections_data,
        sections_zh=sections_zh,
        source_url=paper.abs_url,
        abs_url=paper.abs_url,
        figures_by_section=figures_by_section if not no_figures else None,
        tags=tags,
        has_pdf=not no_pdf,
        arxiv_id=paper.arxiv_id,
        content_type="paper",
    )

    dir_name = fmt.make_paper_dir_name(paper.arxiv_id, paper.title)
    md_path = fmt.write_paper_to_vault(vault_path, papers_folder, dir_name, markdown)
    paper_dir = md_path.parent
    click.echo(f"\nSaved: {md_path}")

    # --- Stage 4: downloads ---
    if not no_pdf:
        pdf_path = paper_dir / "paper.pdf"
        click.echo("Downloading PDF...")
        try:
            arxiv_fetcher.download_pdf(paper.arxiv_id, pdf_path)
            click.echo(f"  PDF: {pdf_path.name}")
        except Exception as e:
            click.echo(f"  Warning: PDF download failed: {e}", err=True)

    if not no_figures and paper.figures:
        figures_dir = paper_dir / "figures"
        click.echo(f"Downloading {len(paper.figures)} figures...")
        ok = sum(
            1 for fig in paper.figures
            if arxiv_fetcher.download_figure(fig, figures_dir / fig.filename)
        )
        click.echo(f"  {ok}/{len(paper.figures)} figures saved")

    v.check_downloads(paper_dir, paper)
    v.check_markdown(paper_dir, markdown)
    _print_issues(v, "post-download")

    click.echo(f"\nDone → {papers_folder}/{dir_name}/index.md")


def _import_pdf(
    path_str: str,
    vault_path: Path,
    papers_folder: str,
    api_key: str,
    model: str,
    extra_tags: list[str],
) -> None:
    import shutil
    v = Validator()

    pdf_path = Path(path_str).expanduser().resolve()
    click.echo(f"Reading PDF: {pdf_path.name}")
    try:
        content = pdf_fetcher.fetch_pdf(pdf_path)
    except Exception as e:
        click.echo(f"Error reading PDF: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Title:    {content.title}")
    click.echo(f"  Authors:  {', '.join(content.authors[:3])}")
    click.echo(f"  Sections: {len(content.sections)}")

    v.check_extraction(content)
    _print_issues(v, "extraction")
    if v.has_errors():
        sys.exit(1)

    abstract_zh, _ = ("", False)
    if content.abstract:
        click.echo("Translating abstract...")
        abstract_zh, abs_cached = trans.translate_abstract(content.abstract, api_key, model)
        if abs_cached:
            click.echo("  (cached)")

    sections_data = [{"title": s.title, "content": s.content} for s in content.sections]
    sections_zh, hits, calls = _translate_with_progress(sections_data, api_key, model)
    _print_cache_stats(hits, calls)

    v.check_translation(sections_data, sections_zh, content.abstract, abstract_zh)
    _print_issues(v, "translation")
    if v.has_errors():
        sys.exit(1)

    tags = ["paper", "pdf"] + extra_tags
    markdown = fmt.generate_markdown(
        title=content.title,
        authors=content.authors,
        year=content.year,
        abstract_en=content.abstract,
        abstract_zh=abstract_zh,
        sections_en=sections_data,
        sections_zh=sections_zh,
        source_url=str(pdf_path),
        abs_url="",
        tags=tags,
        has_pdf=True,
        content_type="paper",
    )

    dir_name = fmt.make_web_dir_name(content.title)
    md_path = fmt.write_paper_to_vault(vault_path, papers_folder, dir_name, markdown)
    paper_dir = md_path.parent

    dest_pdf = paper_dir / "paper.pdf"
    if pdf_path != dest_pdf:
        shutil.copy2(pdf_path, dest_pdf)
        click.echo(f"  PDF copied → {dest_pdf.name}")

    v.check_markdown(paper_dir, markdown)
    _print_issues(v, "post-save")
    click.echo(f"\nDone → {papers_folder}/{dir_name}/index.md")


def _import_generic(
    url: str,
    vault_path: Path,
    papers_folder: str,
    api_key: str,
    model: str,
    extra_tags: list[str],
) -> None:
    v = Validator()

    click.echo(f"Fetching: {url}")
    try:
        content = generic_fetcher.fetch_url(url)
    except Exception as e:
        click.echo(f"Error fetching URL: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Title:    {content.title}")
    click.echo(f"  Sections: {len(content.sections)}")

    v.check_extraction(content)
    _print_issues(v, "extraction")
    if v.has_errors():
        sys.exit(1)

    sections_data = [{"title": s.title, "content": s.content} for s in content.sections]
    sections_zh, hits, calls = _translate_with_progress(sections_data, api_key, model)
    _print_cache_stats(hits, calls)

    v.check_translation(sections_data, sections_zh, "", "")
    _print_issues(v, "translation")
    if v.has_errors():
        sys.exit(1)

    tags = ["article"] + extra_tags
    markdown = fmt.generate_markdown(
        title=content.title,
        authors=content.authors,
        year=content.date[:4] if content.date else "",
        abstract_en="",
        abstract_zh="",
        sections_en=sections_data,
        sections_zh=sections_zh,
        source_url=url,
        abs_url=url,
        tags=tags,
        has_pdf=False,
        content_type="article",
    )

    dir_name = fmt.make_web_dir_name(content.title)
    md_path = fmt.write_paper_to_vault(vault_path, papers_folder, dir_name, markdown)

    v.check_markdown(md_path.parent, markdown)
    _print_issues(v, "post-save")
    click.echo(f"\nDone → {papers_folder}/{dir_name}/index.md")


def _translate_with_progress(
    sections_data: list[dict], api_key: str, model: str
) -> tuple[list[str], int, int]:
    """Translate sections with a progress bar. Returns (translations, cache_hits, api_calls)."""
    sections_zh: list[str] = []
    total_hits = 0
    total_calls = 0
    with click.progressbar(
        sections_data, label="Translating sections", show_eta=True
    ) as bar:
        for sec in bar:
            zh_list, hits, calls = trans.translate_sections([sec], api_key, model)
            sections_zh.extend(zh_list)
            total_hits += hits
            total_calls += calls
    return sections_zh, total_hits, total_calls


def _print_cache_stats(hits: int, calls: int) -> None:
    total = hits + calls
    if total == 0:
        return
    if hits == total:
        click.echo(f"  All {total} sections from cache (0 API calls)")
    elif hits > 0:
        click.echo(f"  Cache: {hits}/{total} hits, {calls} API call(s)")


def _print_issues(v: Validator, stage: str) -> None:
    """Print any new issues from the validator."""
    new = [i for i in v.issues if i.stage in (stage, "extraction", "translation",
                                                "download", "markdown", "post-download",
                                                "post-save")]
    relevant = [i for i in v.issues]
    if not relevant:
        return
    # Only print issues we haven't printed yet — track via a simple set on v
    if not hasattr(v, "_printed"):
        v._printed = set()
    for issue in relevant:
        key = (issue.level, issue.stage, issue.message)
        if key not in v._printed:
            icon = "✗" if issue.level == "ERROR" else "⚠"
            click.echo(f"  {icon} [{issue.stage}] {issue.message}")
            v._printed.add(key)
