"""
flatten_citations.py
--------------------
Joins context_clean.json with references.json to inject the real
ref_paper_id into every citation object so RMLMapper can build
URIs like: https://citekg.org/resource/paper/40dc4c0dfbf0527f

Usage:
    python flatten_citations.py --input context_clean.json --refs  references.json --output context_flat.json
"""

import argparse
import json
import re
from pathlib import Path


def slugify(text: str) -> str:
    """Convert a title to a lowercase underscore string for matching."""
    text = re.sub(r"[^\w\s]", "", text).strip().lower()
    return re.sub(r"\s+", "_", text)[:120]


def build_title_index(references_path: Path) -> dict:
    """Build { slugified_title: paper_id } from references.json."""
    index = {}
    with open(references_path, encoding="utf-8") as f:
        data = json.load(f)

    if "paper" in data:
        t   = data["paper"].get("title", "")
        pid = data["paper"].get("paper_id", "")
        if t and pid:
            index[slugify(t)] = pid

    for ref in data.get("references", []):
        t   = ref.get("title", "")
        pid = ref.get("paper_id", "")
        if t and pid:
            index[slugify(t)] = pid

    return index


def build_context_string(before: str, after: str, marker: str) -> str:
    """Reconstruct the full citation sentence: before + marker + after."""
    before = (before or "").strip()
    after  = (after  or "").strip()
    return f"{before} {marker} {after}"


def flatten(input_path: Path, refs_path: Path, output_path: Path):
    title_index = build_title_index(refs_path)

    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)

    papers    = raw if isinstance(raw, list) else [raw]
    result    = []
    unmatched = []

    for paper in papers:
        paper_id  = paper.get("paper_id", "unknown")
        citations = paper.get("citations", [])
        enriched  = []

        for idx, citation in enumerate(citations):
            marker    = citation.get("citation_marker", f"[{idx}]")
            ref_title = citation.get("reference", {}).get("title", "")
            lctx      = citation.get("local_context", {})

            ref_slug     = slugify(ref_title) if ref_title else ""
            ref_paper_id = title_index.get(ref_slug)

            if not ref_paper_id:
                ref_paper_id = f"unresolved_{ref_slug[:60]}"
                unmatched.append({"citing": paper_id, "marker": marker,
                                  "title": ref_title})

            flat = {
                "paper_id":         paper_id,
                "citation_index":   idx,
                "ref_paper_id":     ref_paper_id,
                "citation_context": build_context_string(
                                        lctx.get("before"),
                                        lctx.get("after"),
                                        marker),
                **citation,
            }
            enriched.append(flat)

        result.append({**paper, "citations": enriched})

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Done. {len(result)} paper(s) written to {output_path}")
    if unmatched:
        print(f"⚠ {len(unmatched)} citations could not be matched to a paper_id:")
        for u in unmatched[:10]:
            print(f"  [{u['marker']}] {u['title'][:70]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input",  default="context_clean.json")
    p.add_argument("--refs",   default="references.json")
    p.add_argument("--output", default="context_flat.json")
    args = p.parse_args()
    flatten(Path(args.input), Path(args.refs), Path(args.output))