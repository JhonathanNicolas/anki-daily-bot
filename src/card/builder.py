from __future__ import annotations

from pathlib import Path


def _load_template(name: str) -> str:
    template_path = Path("templates") / name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    return template_path.read_text(encoding="utf-8")


def render_front(word: str) -> str:
    template = _load_template("front.html")
    return template.replace("{{word}}", word)


def render_back(
    translation: str,
    example: str = "",
    notes: str = "",
    image_filename: str = "",
    audio_filename: str = "",
) -> str:
    template = _load_template("back.html")
    image_html = f'<img src="{image_filename}">' if image_filename else ""
    audio_html = f"[sound:{audio_filename}]" if audio_filename else ""

    return (
        template.replace("{{translation}}", translation)
        .replace("{{example}}", example)
        .replace("{{example_class}}", "" if example else "empty")
        .replace("{{notes}}", notes)
        .replace("{{notes_class}}", "" if notes else "empty")
        .replace("{{image}}", image_html)
        .replace("{{image_class}}", "" if image_filename else "empty")
        .replace("{{audio}}", audio_html)
    )
