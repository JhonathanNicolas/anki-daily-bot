from __future__ import annotations

from abc import ABC, abstractmethod

from src.config.models import SubdeckConfig
from src.card.models import CardData


class AIProvider(ABC):
    @abstractmethod
    def generate_cards(
        self,
        subdeck_config: SubdeckConfig,
        language: str,
        already_known: list[str],
    ) -> list[CardData]:
        """Generate card data for a subdeck, skipping already-known words."""
        ...
