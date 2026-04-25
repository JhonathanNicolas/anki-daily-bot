from __future__ import annotations

from pathlib import Path

import yaml

from src.config.models import DeckConfig


def load_deck_config(path: str | Path) -> DeckConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Deck config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return DeckConfig.model_validate(raw)


def load_all_deck_configs(decks_dir: str | Path = "decks") -> list[DeckConfig]:
    decks_path = Path(decks_dir)
    if not decks_path.exists():
        raise FileNotFoundError(f"Decks directory not found: {decks_path}")

    configs = []
    for yaml_file in sorted(decks_path.glob("*.yaml")):
        configs.append(load_deck_config(yaml_file))
    return configs
