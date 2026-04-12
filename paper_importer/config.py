import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".paper-importer"
CONFIG_FILE = CONFIG_DIR / "config.json"


def get_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_vault_path() -> Path:
    config = get_config()
    vault = config.get("vault_path") or os.environ.get("OBSIDIAN_VAULT_PATH")
    if not vault:
        raise ValueError(
            "Vault path not configured. Run `paper setup` first."
        )
    return Path(vault)


def get_api_key() -> str:
    config = get_config()
    key = config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError(
            "Anthropic API key not configured. Run `paper setup` first."
        )
    return key


def get_papers_folder() -> str:
    config = get_config()
    return config.get("papers_folder", "Papers")
