from __future__ import annotations

_DECK_TO_LANG: dict[str, str] = {
    "german": "de",
    "deutsch": "de",
    "spanish": "es",
    "español": "es",
    "french": "fr",
    "français": "fr",
    "italian": "it",
    "italiano": "it",
    "portuguese": "pt",
    "português": "pt",
    "english": "en",
    "japanese": "ja",
    "chinese": "zh",
    "mandarin": "zh",
    "korean": "ko",
    "arabic": "ar",
    "russian": "ru",
    "dutch": "nl",
    "polish": "pl",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "greek": "el",
    "turkish": "tr",
    "hindi": "hi",
}

_STOP_WORDS = {"the", "a", "an", "of", "in", "at", "to", "for", "word", "words", "phrase"}


def deck_to_language(deck_name: str) -> str:
    """Return BCP-47 language code for a deck name, defaulting to 'en'."""
    return _DECK_TO_LANG.get(deck_name.lower().strip(), "en")


def clean_subdeck_key(raw: str) -> str:
    """
    Derive a clean subdeck key from a topic string.
    Strips 'the word X' patterns and stop words from the front.
    """
    words = raw.lower().split()
    # Strip leading stop words
    while words and words[0] in _STOP_WORDS:
        words = words[1:]
    return words[0] if words else raw.split()[0].lower()
