from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import anthropic
import requests

_UNSPLASH_URL = "https://api.unsplash.com/photos/random"
_POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"

_PROMPT_SYSTEM = """\
You generate concise image prompts for Anki flashcards.
Return ONLY a JSON object with one field: "prompt" (string, max 120 chars).
The image should be clean, educational, and work well as a small flashcard illustration.
"""


class ImageRateLimitError(Exception):
    pass


def _safe_stem(word: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in word).lower()


def _build_ai_prompt(subject: str, context: str, is_stem: bool) -> str:
    """Use Claude to craft a descriptive image prompt."""
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        if is_stem:
            user_msg = (
                f"Create an image prompt for a STEM flashcard about: '{subject}'. "
                f"Context: {context}. "
                f"Style: educational diagram or technical illustration, minimal, white background."
            )
        else:
            user_msg = (
                f"Create an image prompt for a language flashcard illustrating: '{subject}'. "
                f"Style: simple clean illustration, white background, educational."
            )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=_PROMPT_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        data = json.loads(msg.content[0].text.strip())
        return data.get("prompt", subject)
    except Exception:
        # Fallback to a simple descriptive prompt
        if is_stem:
            return f"educational diagram of {subject}, minimal, white background, technical illustration"
        return f"simple illustration of {subject}, clean, white background, educational"


def fetch_image_ai(
    subject: str,
    context: str,
    cache_dir: Path,
    is_stem: bool = False,
) -> Path | None:
    """Generate an image using Pollinations.ai (free, no API key needed)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = f"ai_{subject}_{context}"
    query_hash = hashlib.md5(cache_key.encode()).hexdigest()[:6]
    filename = f"ai_{_safe_stem(subject)}_{query_hash}.jpg"
    dest = cache_dir / filename

    if dest.exists():
        return dest

    prompt = _build_ai_prompt(subject, context, is_stem)
    encoded = quote(prompt)
    url = _POLLINATIONS_URL.format(prompt=encoded) + "?width=512&height=384&nologo=true&model=flux"

    try:
        resp = requests.get(url, timeout=45)
        resp.raise_for_status()
        if len(resp.content) < 1000:  # Pollinations returns tiny error payloads sometimes
            return None
        dest.write_bytes(resp.content)
        return dest
    except requests.RequestException as exc:
        print(f"[media] AI image generation failed for '{subject}': {exc}")
        return None


def fetch_image(query: str, cache_dir: Path, access_key: str | None = None) -> Path | None:
    """Fetch an image from Unsplash (real photos, good for language decks)."""
    key = access_key or os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not key:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    query_hash = hashlib.md5(query.encode()).hexdigest()[:6]
    filename = f"{_safe_stem(query)}_{query_hash}.jpg"
    dest = cache_dir / filename

    if dest.exists():
        return dest

    try:
        resp = requests.get(
            _UNSPLASH_URL,
            params={"query": query, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {key}"},
            timeout=10,
        )
        if resp.status_code == 429:
            raise ImageRateLimitError("Unsplash rate limit reached (50 requests/hour). Try again later.")
        if resp.status_code == 403:
            raise ImageRateLimitError("Unsplash API key is invalid or unauthorized.")
        resp.raise_for_status()
        image_url = resp.json()["urls"]["small"]
        image_resp = requests.get(image_url, timeout=15)
        image_resp.raise_for_status()
        dest.write_bytes(image_resp.content)
        return dest
    except ImageRateLimitError:
        raise
    except requests.RequestException as exc:
        print(f"[media] Could not fetch image for '{query}': {exc}")
        return None
