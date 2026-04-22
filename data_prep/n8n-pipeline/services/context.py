"""
context.py — LLM-Based Context Extraction Service for CiteKG Pipeline 2

Reads:
  <EXTRACTED_DIR>/<folder>/<folder>.md       — full paper text (sent to LLM)
  <EXTRACTED_DIR>/<folder>/references.json   — paper_id, reference list

Returns a dict structured as:
  {
    "paper_id": "",
    "global_context": { "title": "", "abstract": "" },   ← saved ONCE here only
    "citations": [
      {
        "reference": "<title of the referenced paper>",
        "local_context": {
          "before": "",
          "citation_marker": "",
          "after": ""
        }
      }
    ],
    "total_citations": 0,
    "skipped": False
  }
"""

import json
import re
import logging
import requests
from pathlib import Path

from config import EXTRACTED_DIR, LOCAL_LLM_URL, LOCAL_LLM_MODEL

LLM_TIMEOUT = 300   # seconds — full-paper prompts can be slow

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LLM helpers
# ─────────────────────────────────────────────────────────────────────────────

def _call_llm(system_prompt: str, user_prompt: str) -> str:
    payload = {
        "model":         LOCAL_LLM_MODEL,
        "system_prompt": system_prompt,
        "input":         user_prompt,
        "temperature":   0.0,
    }

    resp = requests.post(LOCAL_LLM_URL, json=payload, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()

    # LM Studio output[] format — same as groq.py
    raw = ""
    for type_pref in ("message", "text"):
        for block in body.get("output", []):
            if block.get("type") == type_pref:
                raw = block.get("content", "").strip()
                if raw:
                    break
        if raw:
            break

    if not raw:
        raise ValueError(f"LLM returned no usable content. Body keys: {list(body)}")

    return raw


def _clean_and_parse(raw: str) -> list | dict:
    """Strip <think> tags and markdown fences, then parse JSON — same as groq.py."""
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned non-JSON: {e}\nRaw (first 400 chars): {raw[:400]}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Global context (title + abstract)
# ─────────────────────────────────────────────────────────────────────────────

GLOBAL_SYSTEM = (
    "You are an academic paper parser. "
    "Return ONLY a valid JSON object. No explanations, no markdown, no thinking."
)

GLOBAL_USER = """\
Extract the title and abstract from the academic paper below.

Return exactly this JSON shape — no extra keys:
{{
  "title":    "<full paper title>",
  "abstract": "<full abstract text>"
}}

If you cannot find the abstract, return an empty string for that field.

--- PAPER START ---
{paper_text}
--- PAPER END ---
"""


def _extract_global_context(paper_text: str) -> dict:
    raw    = _call_llm(GLOBAL_SYSTEM, GLOBAL_USER.format(paper_text=paper_text))
    result = _clean_and_parse(raw)
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object for global context, got: {type(result)}")
    return {
        "title":    result.get("title",    "").strip(),
        "abstract": result.get("abstract", "").strip(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Local context (per-citation extraction)
# ─────────────────────────────────────────────────────────────────────────────

LOCAL_SYSTEM = (
    "You are an academic citation context extractor. "
    "Return ONLY a valid JSON array. No explanations, no markdown, no thinking."
)

LOCAL_USER = """\
You are given a full academic paper and its reference list.

Your task: for every place in the paper body where a reference is cited, extract the citation context.

For each citation occurrence return one JSON object in an array:

[
  {{
    "reference_index": <1-based integer matching the reference list below>,
    "citation_marker": "<exact marker as it appears in the paper, e.g. [1] or (Smith, 2019)>",
    "before":          "<verbatim text immediately before the citation marker — up to ~300 tokens>",
    "after":           "<verbatim text immediately after the citation marker — up to ~300 tokens>"
  }},
  ...
]

Rules for "before" and "after":
- Each field must contain verbatim text from the paper — do NOT paraphrase.
- Aim for up to ~300 tokens (~300 words) on each side.
- Start/end on sentence boundaries whenever possible.
- If the citation marker falls near the BEGINNING of its sentence (i.e. there is little or no
  text before the marker within that sentence), also include the 1–2 sentences that precede
  the current sentence, provided the total "before" text does not exceed 300 characters.
- If the citation marker falls near the END of its sentence (i.e. there is little or no
  text after the marker within that sentence), also include the 1–2 sentences that follow
  the current sentence, provided the total "after" text does not exceed 300 characters.
- If there is genuinely no text before/after (e.g. citation at the very start or end of
  a section with nothing adjacent), use an empty string.

Other rules:
- One entry per citation occurrence. If the same reference is cited multiple times, include each occurrence separately.
- Do NOT include entries for references that only appear in the reference list but are never cited in the body.
- Match each citation to the closest reference in the list by title, authors, and year.

--- REFERENCE LIST ---
{reference_list}
--- END REFERENCE LIST ---

--- PAPER START ---
{paper_text}
--- PAPER END ---
"""


def _resolve_author(a) -> str:
    if isinstance(a, str):
        return a
    if isinstance(a, dict):
        return (
            a.get("author_name")
            or a.get("display_name")
            or a.get("name")
            or a.get("author", {}).get("display_name", "")
        )
    return ""


def _build_reference_list(references: list) -> str:
    lines = []
    for i, ref in enumerate(references, start=1):
        raw_authors = ref.get("authors", [])
        authors     = ", ".join(filter(None, (_resolve_author(a) for a in raw_authors))) or "Unknown"
        year        = ref.get("year") or "n.d."
        venue       = ref.get("venue") or ""
        title       = ref.get("title", "Untitled")
        line        = f"[{i}] {authors} ({year}). {title}."
        if venue:
            line += f" {venue}."
        lines.append(line)
    return "\n".join(lines)


def _extract_local_context(paper_text: str, references: list) -> list:
    raw    = _call_llm(LOCAL_SYSTEM, LOCAL_USER.format(
        reference_list=_build_reference_list(references),
        paper_text=paper_text,
    ))
    result = _clean_and_parse(raw)

    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("citations", "results", "data", "items"):
            if isinstance(result.get(key), list):
                return result[key]
    raise ValueError(f"Expected a JSON array for local context, got: {type(result)}")


# ─────────────────────────────────────────────────────────────────────────────
# Assembler
# ─────────────────────────────────────────────────────────────────────────────

def _assemble(paper_id: str, global_context: dict, raw_citations: list, references: list) -> dict:
    citations = []
    for entry in raw_citations:
        idx = entry.get("reference_index")
        if idx is None:
            continue
        try:
            ref = references[int(idx) - 1]
        except (IndexError, ValueError, TypeError):
            logger.warning(f"reference_index {idx} out of range (total: {len(references)})")
            continue

        citations.append({
            # "reference" holds the human-readable title of the cited paper
            "reference": ref.get("title", "Untitled"),
            "local_context": {
                "before":          entry.get("before",          "").strip(),
                "citation_marker": entry.get("citation_marker", "").strip(),
                "after":           entry.get("after",           "").strip(),
            },
            # global_context is NOT repeated here — it lives once at the top level
        })

    return {
        "paper_id":        paper_id,
        "global_context":  global_context,   # ← single copy, at the root
        "citations":       citations,
        "total_citations": len(citations),
        "skipped":         False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — called by the route
# ─────────────────────────────────────────────────────────────────────────────

def extract_context_for_folder(folder_name: str) -> dict:
    folder_path = Path(EXTRACTED_DIR) / folder_name

    if not folder_path.is_dir():
        raise ValueError(f"Folder not found: {folder_path}")

    # Load <folder_name>.md
    md_path = folder_path / f"{folder_name}.md"
    if not md_path.exists():
        raise ValueError(f"{folder_name}.md not found in {folder_path}")

    paper_text = md_path.read_text(encoding="utf-8", errors="replace").strip()
    if not paper_text:
        raise ValueError(f"{folder_name}.md is empty")

    # Load references.json
    refs_path = folder_path / "references.json"
    if not refs_path.exists():
        raise ValueError("references.json not found — run Pipeline 1 first")

    with refs_path.open(encoding="utf-8") as f:
        refs_data = json.load(f)

    paper_meta = refs_data.get("paper", {})
    references = refs_data.get("references", [])
    paper_id   = paper_meta.get("paper_id", folder_name)

    if not references:
        return {
            "paper_id":        paper_id,
            "global_context":  {"title": "", "abstract": ""},
            "citations":       [],
            "total_citations": 0,
            "skipped":         False,
            "note":            "No references in references.json",
        }

    # LLM call 1 — global context
    logger.info(f"[{folder_name}] extracting global context …")
    global_context = _extract_global_context(paper_text)
    logger.info(f"[{folder_name}] title='{global_context['title'][:60]}'")

    # LLM call 2 — local context
    logger.info(f"[{folder_name}] extracting local context for {len(references)} refs …")
    raw_citations = _extract_local_context(paper_text, references)
    logger.info(f"[{folder_name}] LLM returned {len(raw_citations)} citation entries")

    return _assemble(paper_id, global_context, raw_citations, references)