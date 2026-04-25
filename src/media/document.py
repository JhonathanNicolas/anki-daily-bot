from __future__ import annotations

import base64
import os
import re

import anthropic
import httpx


def detect_url(text: str) -> str | None:
    """Return the first URL found in a message, or None."""
    m = re.search(r"https?://[^\s]+", text)
    return m.group(0) if m else None


def extract_from_url(url: str) -> str:
    """Fetch a web page and return its text content."""
    from bs4 import BeautifulSoup

    resp = httpx.get(url, follow_redirects=True, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (compatible; AnkiBot/1.0)"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def extract_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file."""
    import io
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def extract_from_image(image_bytes: bytes, media_type: str = "image/jpeg") -> str:
    """Use Claude Vision to extract text and key information from an image."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    b64 = base64.standard_b64encode(image_bytes).decode()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": (
                    "Extract all text, key concepts, terms, definitions, and important information "
                    "from this image. Be thorough and structured. Output plain text only."
                )},
            ],
        }],
    )
    return message.content[0].text.strip()
