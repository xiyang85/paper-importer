"""
Translation module using Claude API.
Translates text section by section to handle long papers.
Tables are extracted before translation and restored afterwards,
so their content is preserved exactly without being translated.
"""

import re

import anthropic

from . import cache as translation_cache

SYSTEM_PROMPT = """You are a professional academic translator specializing in translating English academic papers into Chinese.

Translation guidelines:
- Produce fluent, natural Chinese that reads well academically
- Preserve technical terms: keep widely-used English terms (e.g., Transformer, attention mechanism, loss function, gradient) in English, add Chinese explanation on first occurrence if helpful
- Preserve all numbers, formula references (e.g., "Equation (1)", "Figure 2"), and citation markers (e.g., "[3]", "[Smith et al., 2020]")
- Preserve paragraph structure — one English paragraph → one Chinese paragraph
- Do not add explanations, commentary, or any text not in the original
- Output ONLY the translated text, nothing else"""

_PLACEHOLDER_PREFIX = "PAPER_IMPORTER_TABLE_"


def translate_sections(
    sections: list[dict],
    api_key: str,
    model: str = "claude-opus-4-6",
) -> tuple[list[str], int, int]:
    """Translate sections, using cache where available.

    Returns:
        (translations, cache_hits, api_calls)
    """
    client = anthropic.Anthropic(api_key=api_key)
    translations = []
    cache_hits = 0
    api_calls = 0

    for section in sections:
        text = section.get("content", "").strip()
        if not text:
            translations.append("")
            continue

        cached = translation_cache.get(model, text)
        if cached is not None:
            translations.append(cached)
            cache_hits += 1
        else:
            result = _translate_text(client, text, model)
            translation_cache.set(model, text, result)
            translations.append(result)
            api_calls += 1

    return translations, cache_hits, api_calls


def translate_abstract(abstract: str, api_key: str, model: str = "claude-opus-4-6") -> tuple[str, bool]:
    """Translate abstract. Returns (translation, from_cache)."""
    if not abstract.strip():
        return "", False
    cached = translation_cache.get(model, abstract)
    if cached is not None:
        return cached, True
    client = anthropic.Anthropic(api_key=api_key)
    result = _translate_text(client, abstract, model)
    translation_cache.set(model, abstract, result)
    return result, False


def _translate_text(client: anthropic.Anthropic, text: str, model: str) -> str:
    """Translate text, preserving Markdown tables exactly as-is."""
    cleaned, tables = _extract_tables(text)

    # If everything was tables (e.g. a section with only a table), return as-is
    if not cleaned.strip():
        return text

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": cleaned}],
    )
    translated = message.content[0].text.strip()
    return _restore_tables(translated, tables)


def _extract_tables(text: str) -> tuple[str, list[str]]:
    """Replace Markdown table blocks with numbered placeholders.

    A table block is one or more consecutive lines beginning with '|',
    optionally preceded by a bold caption line (**Table N: ...**).
    Returns (text_with_placeholders, list_of_original_table_strings).
    """
    tables: list[str] = []
    paragraphs = text.split("\n\n")
    result: list[str] = []

    for para in paragraphs:
        if _is_table_block(para):
            result.append(f"{_PLACEHOLDER_PREFIX}{len(tables)}")
            tables.append(para)
        else:
            result.append(para)

    return "\n\n".join(result), tables


def _restore_tables(text: str, tables: list[str]) -> str:
    for i, table in enumerate(tables):
        text = text.replace(f"{_PLACEHOLDER_PREFIX}{i}", table)
    return text


def _is_table_block(para: str) -> bool:
    """Return True if the paragraph contains a Markdown table separator row."""
    return bool(re.search(r"^\| ?[-:]+", para, re.MULTILINE))
