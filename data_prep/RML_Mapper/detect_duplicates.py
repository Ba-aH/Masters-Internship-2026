"""
detect_duplicates.py
--------------------
Detects duplicate references in references.json.

Three levels of detection:
  1. Exact   — same paper_id
  2. Soft    — same openalex_id (different paper_id assigned by your extractor)
  3. Fuzzy   — same slugified title (catches typos / capitalisation differences)

Usage:
    python detect_duplicates.py --input references.json
    python detect_duplicates.py --input references.json --fix --output references_deduped.json
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text).strip().lower()
    return re.sub(r"\s+", "_", text)


def first_author(ref: dict) -> str:
    authors = ref.get("authors", [])
    if authors:
        return authors[0].get("name", "")
    return ""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect(references: list[dict]) -> dict:
    """
    Returns a report dict with three duplicate groups:
      by_paper_id    — list of groups sharing the same paper_id
      by_openalex_id — list of groups sharing the same openalex_id
      by_title       — list of groups sharing the same slugified title
    """

    # --- group by paper_id ---
    paper_id_groups = defaultdict(list)
    for i, ref in enumerate(references):
        pid = ref.get("paper_id")
        if pid:
            paper_id_groups[pid].append(i)

    # --- group by openalex_id ---
    openalex_groups = defaultdict(list)
    for i, ref in enumerate(references):
        oid = ref.get("openalex_id")
        if oid:
            openalex_groups[oid].append(i)

    # --- group by title slug ---
    title_groups = defaultdict(list)
    for i, ref in enumerate(references):
        t = ref.get("title", "")
        if t:
            title_groups[slugify(t)].append(i)

    def make_groups(groups: dict) -> list:
        return [
            {
                "key":   key,
                "count": len(idxs),
                "entries": [
                    {
                        "index":        idx,
                        "paper_id":     references[idx].get("paper_id"),
                        "title":        references[idx].get("title"),
                        "year":         references[idx].get("year"),
                        "venue":        references[idx].get("venue"),
                        "openalex_id":  references[idx].get("openalex_id"),
                        "first_author": first_author(references[idx]),
                    }
                    for idx in idxs
                ],
            }
            for key, idxs in groups.items()
            if len(idxs) > 1          # only actual duplicates
        ]

    return {
        "by_paper_id":    make_groups(paper_id_groups),
        "by_openalex_id": make_groups(openalex_groups),
        "by_title":       make_groups(title_groups),
    }


# ---------------------------------------------------------------------------
# Fix — keep one entry per paper_id (the one with most data)
# ---------------------------------------------------------------------------

def score_ref(ref: dict) -> int:
    """Score a reference by how complete its data is. Higher = better."""
    score = 0
    if ref.get("doi"):                          score += 3
    if ref.get("openalex_id"):                  score += 3
    if ref.get("openalex_title_validated"):     score += 2
    if ref.get("year"):                         score += 1
    if ref.get("venue"):                        score += 1
    if ref.get("citation_count") is not None:   score += 1
    score += len(ref.get("authors", []))
    return score


def deduplicate(references: list[dict]) -> tuple[list[dict], int]:
    """
    Keeps the best-scored entry for each paper_id.
    Returns (deduped_list, number_removed).
    """
    seen     = {}   # paper_id → best ref so far
    removed  = 0

    for ref in references:
        pid = ref.get("paper_id")
        if not pid:
            # No paper_id — keep as-is
            seen[id(ref)] = ref
            continue

        if pid not in seen:
            seen[pid] = ref
        else:
            removed += 1
            # Keep the one with more complete data
            if score_ref(ref) > score_ref(seen[pid]):
                seen[pid] = ref

    return list(seen.values()), removed


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(report: dict, references: list[dict]):
    total = len(references)

    pid_dups   = report["by_paper_id"]
    oid_dups   = report["by_openalex_id"]
    title_dups = report["by_title"]

    # Count how many individual entries are duplicates
    dup_entries = sum(g["count"] - 1 for g in pid_dups)

    print(f"\n{'='*60}")
    print(f"  DUPLICATE REPORT")
    print(f"{'='*60}")
    print(f"  Total references : {total}")
    print(f"  Duplicate entries: {dup_entries}  (would be removed by --fix)")
    print(f"  Unique papers    : {total - dup_entries}")
    print()

    # --- by paper_id ---
    print(f"── BY paper_id ({len(pid_dups)} groups) {'─'*30}")
    if not pid_dups:
        print("  None found.")
    for g in pid_dups:
        print(f"\n  paper_id: {g['key']}  ({g['count']} occurrences)")
        for e in g["entries"]:
            print(f"    [{e['index']:>3}]  year={e['year']}  "
                  f"venue={str(e['venue'])[:40]:<40}  "
                  f"title={str(e['title'])[:50]}")

    # --- by openalex_id ---
    print(f"\n── BY openalex_id ({len(oid_dups)} groups) {'─'*28}")
    # Filter out groups already covered by paper_id duplicates
    pid_keys = {g["key"] for g in pid_dups}
    extra_oid = [
        g for g in oid_dups
        if not any(e["paper_id"] in pid_keys for e in g["entries"])
    ]
    if not extra_oid:
        print("  None beyond those already caught by paper_id.")
    for g in extra_oid:
        print(f"\n  openalex_id: {g['key']}  ({g['count']} occurrences)")
        for e in g["entries"]:
            print(f"    [{e['index']:>3}]  paper_id={e['paper_id']}  "
                  f"title={str(e['title'])[:50]}")

    # --- by title ---
    print(f"\n── BY title slug ({len(title_dups)} groups) {'─'*29}")
    extra_title = [
        g for g in title_dups
        if not any(e["paper_id"] in pid_keys for e in g["entries"])
    ]
    if not extra_title:
        print("  None beyond those already caught by paper_id.")
    for g in extra_title:
        print(f"\n  title: \"{g['entries'][0]['title'][:60]}\"  ({g['count']} occurrences)")
        for e in g["entries"]:
            print(f"    [{e['index']:>3}]  paper_id={e['paper_id']}  "
                  f"openalex={str(e['openalex_id'])[:45]}")

    print(f"\n{'='*60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input",  default="references.json")
    p.add_argument("--output", default="references_deduped.json",
                   help="Output path (only used with --fix)")
    p.add_argument("--fix",    action="store_true",
                   help="Write a deduplicated version of the file")
    args = p.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    references = data.get("references", [])
    report     = detect(references)
    print_report(report, references)

    if args.fix:
        deduped, removed = deduplicate(references)
        data["references"] = deduped

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"Fixed file written to: {args.output}")
        print(f"Removed {removed} duplicate entries.")
        print(f"References: {len(references)} → {len(deduped)}\n")


if __name__ == "__main__":
    main()
