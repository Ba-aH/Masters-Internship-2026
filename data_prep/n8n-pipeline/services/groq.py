import json
import re
import threading

import requests

from config import GROQ_API_KEYS, GROQ_MODEL, LINES_PER_CHUNK

_groq_key_index = 0
_groq_key_lock  = threading.Lock()


def _get_groq_api_key() -> str:
    """Return the next Groq API key, rotating round-robin across all keys."""
    global _groq_key_index
    with _groq_key_lock:
        key = GROQ_API_KEYS[_groq_key_index % len(GROQ_API_KEYS)]
        _groq_key_index += 1
    return key


def split_into_chunks(text: str) -> list[str]:
    """
    Split reference text into chunks at LINE boundaries (never mid-entry).
    Each chunk has at most LINES_PER_CHUNK lines.
    """
    lines = text.splitlines()
    chunks = []
    for i in range(0, len(lines), LINES_PER_CHUNK):
        chunk = "\n".join(lines[i:i + LINES_PER_CHUNK]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks if chunks else [text]


def call_groq(raw_content: str) -> list:
    """
    Send one chunk to the Groq API and return a list of parsed reference dicts.
    Raises requests.HTTPError on 4xx / 5xx responses.
    """
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {_get_groq_api_key()}",
        "User-Agent":    "Mozilla/5.0",   # urllib UA is blocked by Cloudflare
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role":    "system",
                "content": "You are an expert academic reference extractor and cleaner. Always respond with valid JSON only.",
            },
            {
                "role": "user",
                "content": (
                    "Extract and clean the following messy reference list into a JSON array of references.\n\n"
                    "Each reference must have these fields:\n"
                    "- title (string, required)\n"
                    "- authors (array of strings)\n"
                    "- year (number or null)\n"
                    "- venue (string or null)\n\n"
                    "Rules:\n"
                    "- Split merged references into separate entries\n"
                    "- Clean and correct obvious errors in titles and author names\n"
                    "- Return ONLY a valid JSON array like: [ { \"title\": \"...\", \"authors\": [...], ... }, ... ]\n"
                    "- Do not add any extra text, explanations, or markdown.\n\n"
                    f"Here is the messy reference list:\n\n{raw_content}"
                ),
            },
        ],
        "temperature":     0.1,
        "max_tokens":      2500,
        "response_format": {"type": "json_object"},
    }

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"]
    raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$',       '', raw.strip())

    parsed = json.loads(raw)

    if isinstance(parsed, dict):
        for key in ("references", "data", "items", "results"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        return [parsed]

    if isinstance(parsed, list):
        return parsed

    return [{"title": "Parsing failed", "authors": [], "raw": raw}]