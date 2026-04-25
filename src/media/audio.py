from __future__ import annotations

import hashlib
from pathlib import Path

from gtts import gTTS

_LANG_MAP: dict[str, str] = {
    "de": "de",
    "es": "es",
    "fr": "fr",
    "it": "it",
    "pt": "pt",
    "en": "en",
    "ja": "ja",
    "zh": "zh",
}


def _safe_stem(word: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in word).lower()


def generate_audio(word: str, language_code: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    lang = _LANG_MAP.get(language_code, language_code)
    word_hash = hashlib.md5(word.encode()).hexdigest()[:6]
    filename = f"{_safe_stem(word)}_{word_hash}.mp3"
    dest = cache_dir / filename

    if not dest.exists():
        tts = gTTS(text=word, lang=lang)
        tts.save(str(dest))

    return dest
