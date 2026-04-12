"""
Translation module using Claude API.
Translates text section by section to handle long papers.
"""

import anthropic

SYSTEM_PROMPT = """You are a professional academic translator specializing in translating English academic papers into Chinese.

Translation guidelines:
- Produce fluent, natural Chinese that reads well academically
- Preserve technical terms: keep widely-used English terms (e.g., Transformer, attention mechanism, loss function, gradient) in English, add Chinese explanation on first occurrence if helpful
- Preserve all numbers, formulas references (e.g., "Equation (1)", "Figure 2"), and citation markers (e.g., "[3]", "[Smith et al., 2020]")
- Preserve paragraph structure — one English paragraph → one Chinese paragraph
- Do not add explanations, commentary, or any text not in the original
- Output ONLY the translated text, nothing else"""


def translate_sections(
    sections: list[dict],
    api_key: str,
    model: str = "claude-opus-4-6",
) -> list[str]:
    """
    Translate a list of sections.

    Args:
        sections: list of dicts with 'title' and 'content' keys
        api_key: Anthropic API key
        model: Claude model to use

    Returns:
        list of translated content strings (same order as input)
    """
    client = anthropic.Anthropic(api_key=api_key)
    translations = []

    for section in sections:
        text = section.get("content", "").strip()
        if not text:
            translations.append("")
            continue

        translated = _translate_text(client, text, model)
        translations.append(translated)

    return translations


def translate_abstract(abstract: str, api_key: str, model: str = "claude-opus-4-6") -> str:
    """Translate just the abstract."""
    if not abstract.strip():
        return ""
    client = anthropic.Anthropic(api_key=api_key)
    return _translate_text(client, abstract, model)


def _translate_text(client: anthropic.Anthropic, text: str, model: str) -> str:
    """Translate a single block of text."""
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": text,
            }
        ],
    )
    return message.content[0].text.strip()
