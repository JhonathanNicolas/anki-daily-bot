from __future__ import annotations

import base64
import os
import re

import anthropic
import httpx

# Maps file extension → canonical language name
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".rs": "rust",
    ".go": "go",
    ".cs": "csharp",
    ".rb": "ruby",
    ".v": "verilog", ".sv": "systemverilog",
    ".vhd": "vhdl", ".vhdl": "vhdl",
    ".asm": "assembly", ".s": "assembly",
    ".m": "matlab",
    ".r": "r",
    ".lua": "lua",
    ".sh": "bash", ".bash": "bash",
}

# Normalise user-typed language names to canonical form
_LANGUAGE_ALIASES: dict[str, str] = {
    "c++": "cpp", "c sharp": "csharp", "c#": "csharp",
    "system verilog": "systemverilog", "system-verilog": "systemverilog",
    "bash": "bash", "shell": "bash",
    "asm": "assembly",
}

CODE_EXTENSIONS = set(_EXT_TO_LANGUAGE.keys())


def language_from_extension(filename: str) -> str | None:
    """Return canonical language name for a filename/path, or None."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXT_TO_LANGUAGE.get(ext)


def normalise_language(lang: str) -> str:
    """Normalise a user-typed language name to canonical form."""
    cleaned = lang.strip().lower()
    return _LANGUAGE_ALIASES.get(cleaned, cleaned)


def validate_code_file(filename: str, deck_language: str | None) -> str | None:
    """Return an error message if the file language doesn't match the deck, else None."""
    file_lang = language_from_extension(filename)
    if file_lang is None:
        return f"Unsupported file type `{filename}`. Supported: {', '.join(sorted(CODE_EXTENSIONS))}"
    if deck_language:
        deck_lang = normalise_language(deck_language)
        if file_lang != deck_lang:
            return (
                f"File `{filename}` is *{file_lang.upper()}* but this deck is configured for "
                f"*{deck_lang.upper()}*. Please send a `{deck_lang}` file."
            )
    return None


def extract_from_code_file(file_bytes: bytes) -> str:
    """Read a code file as UTF-8 text."""
    return file_bytes.decode("utf-8", errors="replace")


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
