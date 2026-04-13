"""
Translation cache — persists section-level translations to disk.

Key  = SHA256(model + "\n" + english_text)
Value = translated Chinese text

Stored in ~/.paper-importer/translation_cache.json.
The cache is append-only; entries are never evicted automatically.
"""

import hashlib
import json
import os
from pathlib import Path

from . import config as cfg

_CACHE_FILE = cfg.CONFIG_DIR / "translation_cache.json"
_cache: dict[str, str] | None = None  # in-memory mirror


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    if _CACHE_FILE.exists():
        with open(_CACHE_FILE, encoding="utf-8") as f:
            _cache = json.load(f)
    else:
        _cache = {}
    return _cache


def _save() -> None:
    cfg.CONFIG_DIR.mkdir(exist_ok=True)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def make_key(model: str, english_text: str) -> str:
    raw = f"{model}\n{english_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(model: str, english_text: str) -> str | None:
    """Return cached translation, or None if not cached."""
    return _load().get(make_key(model, english_text))


def set(model: str, english_text: str, translation: str) -> None:
    """Store a translation in the cache and flush to disk."""
    _load()[make_key(model, english_text)] = translation
    _save()


def stats() -> dict:
    data = _load()
    size = _CACHE_FILE.stat().st_size if _CACHE_FILE.exists() else 0
    return {
        "entries": len(data),
        "file": str(_CACHE_FILE),
        "size_kb": round(size / 1024, 1),
    }
